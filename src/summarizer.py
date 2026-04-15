#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Summarize agent output for spoken TTS updates.

The default backend is a resident local MLX summarizer daemon. If that daemon
is not warm, we fall back to the deterministic local summarizer so hooks stay
fast and do not cold-load a model. The old `claude -p` path remains available
through `summary_backend: "claude"` or HANDSFREE_SUMMARY_BACKEND=claude.
"""

from __future__ import annotations

import os
import json
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# Allow imports from src/ when run from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent))

from chatterbox_markup import CHATTERBOX_PROMPT_GUIDANCE
from config import SUMMARY_SOCKET, get_config

PROMPTS = {
    "terse": (
        "You are a voice assistant giving a spoken status update to a developer. "
        "One sentence max. Lead with what matters: do you need their input, or is everything fine? "
        "Never read out file names, paths, or code. "
        f"{CHATTERBOX_PROMPT_GUIDANCE} "
        "Here is Claude's output:\n\n"
    ),
    "tiny": (
        "You are a voice assistant giving a very short spoken status update to a developer. "
        "Return 5 to 10 words, one sentence max. Lead with the concrete outcome. "
        "Never read out file names, paths, code, or test counts. "
        f"{CHATTERBOX_PROMPT_GUIDANCE} "
        "Here is Claude's output:\n\n"
    ),
    "detailed": (
        "You are a voice assistant giving a spoken status update to a developer "
        "wearing AirPods who is away from their desk. Rules:\n"
        "- Lead with whether you need their input or not.\n"
        "- If Claude is asking the user a question or presenting choices, "
        "clearly state the question and read out each option. "
        "For example: 'I need your input. Which database should we use? "
        "Option A: Postgres. Option B: SQLite. Option C: Redis.'\n"
        "- If no question, briefly cover ALL the meaningful changes or actions, not just one. "
        "For example: 'No input needed. I updated the summarizer prompts to be less verbose and bumped the TTS speed.'\n"
        "- Don't cherry-pick one change and ignore others.\n"
        "- NEVER read out file names, file paths, function names, or code.\n"
        "- Speak naturally like a coworker giving a quick update.\n"
        f"- {CHATTERBOX_PROMPT_GUIDANCE}\n"
        "- 2-3 sentences max.\n"
        "Here is Claude's output:\n\n"
    ),
}

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_ABS_PATH_RE = re.compile(r"(?:~|/[\w .@+-]+)(?:/[\w .@+-]+)+")
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BULLET_RE = re.compile(r"(?m)^\s*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")
_QUESTION_HINTS = (
    "do you want",
    "would you like",
    "would you rather",
    "what should",
    "should i",
    "should we",
    "can you",
    "please confirm",
    "need your input",
    "needs your input",
    "waiting for your input",
)
_QUESTION_SENTENCE_RE = re.compile(
    r"(?:^|[.!?]\s+)"
    r"(?:which|what|how)\b"
    r"[^.!?]{0,160}\b"
    r"(?:should|want|prefer|choose|pick|select|use|run|do|proceed)\b",
    re.IGNORECASE,
)
_PREFIXES = ("no input needed", "i need your input")
VALID_VERBOSITIES = {"direct", "detailed", "terse", "tiny"}


def _normalize_verbosity(verbosity: str | None) -> str:
    if verbosity in VALID_VERBOSITIES:
        return str(verbosity)
    return "detailed"


def _limit_for_verbosity(verbosity: str) -> int:
    if verbosity == "tiny":
        return 140
    if verbosity == "terse":
        return 220
    return 420


def _max_sentences_for_verbosity(verbosity: str) -> int:
    if verbosity in {"terse", "tiny"}:
        return 1
    return 2


def _resolve_claude_bin() -> str | None:
    """Find a usable Claude CLI binary path."""
    # Explicit override for non-standard installs.
    override = os.environ.get("HANDSFREE_CLAUDE_BIN")
    if override:
        path = Path(override).expanduser()
        if path.exists():
            return str(path)

    found = shutil.which("claude")
    if found:
        return found

    fallback = Path.home() / ".local" / "bin" / "claude"
    if fallback.exists():
        return str(fallback)

    return None


def _clean_for_voice(text: str) -> str:
    """Strip markup and code-heavy content that sounds bad over TTS."""

    text = _CODE_FENCE_RE.sub(" I included code or commands in the response. ", text)
    text = _MARKDOWN_LINK_RE.sub(r"\1", text)

    def _inline_code_repl(match: re.Match[str]) -> str:
        value = match.group(1).strip()
        if "/" in value or "." in value or len(value) > 28:
            return "the relevant file"
        return value

    text = _INLINE_CODE_RE.sub(_inline_code_repl, text)
    text = _ABS_PATH_RE.sub("the relevant file", text)
    text = _BULLET_RE.sub("", text)
    text = re.sub(r"[*_#>]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _cap_words(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].strip()
    if not clipped:
        return text[:limit].strip()
    return clipped.rstrip(".!?") + "."


def _sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for match in _SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        if len(sentence.split()) < 3 and not sentence.endswith("?"):
            continue
        sentences.append(sentence)
    return sentences


def _needs_input(cleaned: str) -> bool:
    lowered = cleaned.lower()
    return (
        "?" in cleaned
        or any(hint in lowered for hint in _QUESTION_HINTS)
        or bool(_QUESTION_SENTENCE_RE.search(cleaned))
    )


def _input_request_text(cleaned: str) -> str:
    """Return the concrete user-facing request from an input-needed update."""

    sentences = _sentences(cleaned)
    for sentence in reversed(sentences):
        if sentence.rstrip().endswith("?"):
            return sentence

    for sentence in reversed(sentences):
        lowered = sentence.lower()
        if any(hint in lowered for hint in _QUESTION_HINTS) or _QUESTION_SENTENCE_RE.search(sentence):
            return sentence

    return ""


def _strip_spoken_prefix(text: str) -> str:
    stripped = text.strip()
    lowered = stripped.lower()
    for prefix in _PREFIXES:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].lstrip(" .:")
    return stripped


def _summary_mode(cleaned: str) -> str:
    return "choice" if _needs_input(cleaned) else "status"


def summarize_local(text: str, verbosity: str = "detailed") -> str:
    """Cheap deterministic spoken digest with no model call."""

    verbosity = _normalize_verbosity(verbosity)
    cleaned = _clean_for_voice(text)
    if not cleaned:
        return ""
    if verbosity == "direct":
        return cleaned

    lowered = cleaned.lower()
    has_existing_prefix = lowered.startswith(("no input needed", "i need your input"))
    needs_input = _needs_input(cleaned)
    prefix = "" if has_existing_prefix else (
        "I need your input. " if needs_input else "No input needed. "
    )
    limit = _limit_for_verbosity(verbosity)

    if needs_input and not has_existing_prefix:
        request = _input_request_text(cleaned)
        if request:
            return _cap_words(prefix + _strip_spoken_prefix(request), limit)

    max_sentences = _max_sentences_for_verbosity(verbosity)
    chosen: list[str] = []
    for sentence in _sentences(cleaned):
        if has_existing_prefix and sentence.lower().startswith(
            ("no input needed", "i need your input")
        ):
            chosen.append(sentence)
        elif sentence not in chosen:
            chosen.append(sentence)
        if len(chosen) >= max_sentences:
            break

    if not chosen:
        chosen = [cleaned]

    return _cap_words(prefix + " ".join(chosen), limit)


def summarize_claude(text: str, verbosity: str = "detailed") -> str:
    """Summarize text via claude -p. Returns the summary string."""

    if not text or not text.strip():
        return ""

    verbosity = _normalize_verbosity(verbosity)
    if verbosity == "direct":
        return summarize_local(text, verbosity=verbosity)

    prompt_prefix = PROMPTS.get(verbosity, PROMPTS["detailed"])
    full_prompt = prompt_prefix + text

    try:
        claude_bin = _resolve_claude_bin()
        if not claude_bin:
            print(
                "[handsfree] claude binary not found. Set HANDSFREE_CLAUDE_BIN or add claude to PATH.",
                file=sys.stderr,
            )
            return summarize_local(text, verbosity=verbosity)
        # Pass HANDSFREE_ACTIVE env var so claude -p's hooks know not to recurse.
        # Use stdin ("-p -") to avoid OS arg-size limits on long transcripts.
        env = {**os.environ, "HANDSFREE_ACTIVE": "1"}
        result = subprocess.run(
            [claude_bin, "-p", "-"],
            input=full_prompt,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        else:
            # Fallback: return a truncated version of the original
            return summarize_local(text, verbosity=verbosity)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"[handsfree] claude -p failed: {e}", file=sys.stderr)
        return summarize_local(text, verbosity=verbosity)


def _request_mlx_summary(
    text: str,
    *,
    mode: str,
    verbosity: str,
    timeout: float = 0.35,
) -> str:
    """Request a prefix-free summary from the resident MLX daemon."""

    payload = {
        "command": "summarize",
        "text": text,
        "mode": mode,
        "verbosity": verbosity,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(SUMMARY_SOCKET))
        client.settimeout(15.0)
        client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    raw = b"".join(chunks).split(b"\n", 1)[0]
    response = json.loads(raw.decode("utf-8"))
    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "MLX summarizer failed"))
    return str(response.get("summary") or "").strip()


def summarize_mlx(text: str, verbosity: str = "detailed") -> str:
    """Summarize using the resident local MLX daemon, with local fallback."""

    verbosity = _normalize_verbosity(verbosity)
    cleaned = _clean_for_voice(text)
    if not cleaned:
        return ""
    if verbosity == "direct":
        return cleaned

    needs_input = _needs_input(cleaned)
    prefix = "I need your input." if needs_input else "No input needed."
    mode = _summary_mode(cleaned)
    limit = _limit_for_verbosity(verbosity)

    if needs_input:
        request = _input_request_text(cleaned)
        if request:
            return _cap_words(f"{prefix} {_strip_spoken_prefix(request)}", limit)

    try:
        model_summary = _request_mlx_summary(
            cleaned,
            mode=mode,
            verbosity=verbosity,
        )
    except (OSError, TimeoutError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        if os.environ.get("HANDSFREE_DEBUG"):
            print(f"[handsfree] MLX summarizer unavailable: {exc}", file=sys.stderr)
        return summarize_local(cleaned, verbosity=verbosity)

    model_summary = _clean_for_voice(_strip_spoken_prefix(model_summary))
    if not model_summary:
        return summarize_local(cleaned, verbosity=verbosity)

    return _cap_words(f"{prefix} {model_summary}", limit)


def summarize(
    text: str,
    verbosity: str | None = None,
    backend: str | None = None,
) -> str:
    """Summarize text for speech using the configured backend."""

    if not text or not text.strip():
        return ""

    config = get_config()
    if verbosity is None:
        verbosity = config.get("verbosity", "detailed")
    verbosity = _normalize_verbosity(verbosity)
    if backend is None:
        backend = config.get("summary_backend", "mlx")

    if backend == "claude":
        return summarize_claude(text, verbosity=verbosity)
    if backend == "mlx":
        return summarize_mlx(text, verbosity=verbosity)
    return summarize_local(text, verbosity=verbosity)


if __name__ == "__main__":
    # Read from stdin or use argv
    if not sys.stdin.isatty():
        input_text = sys.stdin.read()
    elif len(sys.argv) > 1:
        input_text = " ".join(sys.argv[1:])
    else:
        print("Usage: echo 'text' | uv run src/summarizer.py")
        print("   or: uv run src/summarizer.py 'text to summarize'")
        sys.exit(1)

    summary = summarize(input_text)
    print(summary)
