"""Shared Chatterbox speech markup vocabulary and sanitizing helpers."""

from __future__ import annotations

import re

EMOTION_TAGS = (
    "angry",
    "fear",
    "surprised",
    "whispering",
    "advertisement",
    "dramatic",
    "narration",
    "crying",
    "happy",
    "sarcastic",
)

SOUND_EFFECT_TAGS = (
    "clear throat",
    "sigh",
    "shush",
    "cough",
    "groan",
    "sniff",
    "gasp",
    "chuckle",
    "laugh",
)

CHATTERBOX_TAGS = frozenset((*EMOTION_TAGS, *SOUND_EFFECT_TAGS))

CHATTERBOX_PROMPT_GUIDANCE = (
    "Chatterbox TTS supports bracketed speech tags. "
    f"Emotion tags: {', '.join(f'[{tag}]' for tag in EMOTION_TAGS)}. "
    f"Sound effect tags: {', '.join(f'[{tag}]' for tag in SOUND_EFFECT_TAGS)}. "
    "Use tags sparingly and only when the words justify the performance: "
    "for example [sigh] before an apology or failure, [happy] for relief after success, "
    "[chuckle] or [laugh] only when something is actually funny, and [dramatic] for real stakes. "
    "Put a tag immediately before the sentence or phrase it colors. "
    "Use at most one tag in a terse update and at most two tags in a longer spoken answer. "
    "Do not invent tags, and do not tag neutral status text."
)

_CHATTERBOX_LIKE_TAG_RE = re.compile(r"\[([A-Za-z][A-Za-z -]{0,39})\]")


def normalize_chatterbox_tag(value: str) -> str:
    """Normalize model-emitted tag text to the canonical Chatterbox spelling."""

    return re.sub(r"\s+", " ", value.strip().lower().replace("_", " "))


def extract_chatterbox_tags(text: str) -> list[str]:
    """Return the valid Chatterbox tags present in text, in speech order."""

    tags: list[str] = []
    for match in _CHATTERBOX_LIKE_TAG_RE.finditer(text):
        tag = normalize_chatterbox_tag(match.group(1))
        if tag in CHATTERBOX_TAGS:
            tags.append(tag)
    return tags


def sanitize_chatterbox_markup(
    text: str,
    *,
    allow_tags: bool,
    max_tags: int | None = None,
) -> str:
    """Preserve valid Chatterbox tags up to a budget and strip tag-like markup.

    Unknown bracketed alpha tags are removed so a model cannot make Kokoro or
    macOS `say` read "[excited]" aloud, and cannot send unsupported tags to
    Chatterbox.
    """

    if not text:
        return text

    tags_used = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal tags_used

        tag = normalize_chatterbox_tag(match.group(1))
        if tag not in CHATTERBOX_TAGS:
            return ""
        if not allow_tags:
            return ""
        if max_tags is not None and tags_used >= max(0, max_tags):
            return ""
        tags_used += 1
        return f"[{tag}]"

    cleaned = _CHATTERBOX_LIKE_TAG_RE.sub(replace, text)
    cleaned = re.sub(r"[ \t]+([.,!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()
