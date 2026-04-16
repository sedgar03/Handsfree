# Handsfree Voice Prompts

This folder holds the editable prompts that shape what Handsfree says. The
normal text-to-speech layer does not use an LLM prompt; it only speaks the final
string. These files control the model steps that create that string.

## I want agent progress read aloud

Speech mode compresses Claude, Codex, or other agent output into a short spoken
update.

Prompts used:

- `summary_system.md`
- `chatterbox_guidance.md`

Edit `summary_system.md` when updates are too wordy, omit important status, or
read too much implementation detail aloud.

Useful verbosity values:

- `tiny`: quick ping
- `terse`: one-line status
- `detailed`: normal spoken update
- `expanded`: fuller document/research update
- `direct`: cleaned direct readout

## I want to ask what happened later

Wake/on-demand queue reading usually speaks the already-summarized queue event.
It does not normally call the conductor unless conductor routing is enabled.

Prompt used:

- usually none beyond the prior summary prompt

## I want to talk to the conductor

Conductor mode handles freeform voice requests, such as planning, asking about
tmux panes, or thinking through a document.

Prompts used:

- `conductor_system.md`
- `chatterbox_guidance.md`

Edit `conductor_system.md` to change the local assistant's general role,
personality, caution, or delegation style.

To view the conductor conversation while it runs:

```text
PYTHONPATH=src uv run python -m broker conductor pane
```

When run inside tmux, this opens a `handsfree-conductor` window in the current
session. When run outside tmux, it prints an `attach_command` you can run or put
behind a HUD copy button.

To watch in the current terminal instead:

```text
PYTHONPATH=src uv run python -m broker conductor watch --conversation-id voice
```

## I want conductor-styled queue readouts

When conductor routing is enabled, an existing queue event can be rewritten
before speech. This is still conductor mode, but the job is narrower: preserve
the event facts and produce the exact spoken response.

Prompts used:

- `conductor_system.md`
- `conductor_event_response.md`
- `chatterbox_guidance.md`

Edit `conductor_event_response.md` when queued events sound awkward or lose
required actions such as allow-or-deny permission instructions.

## I only want raw TTS

Raw TTS uses no prompt. `src/tts.py` receives a string and speaks it through the
configured provider.

## Override Locally

Repo prompt files are the defaults. To experiment without changing the repo,
put a file with the same name under:

```text
~/.handsfree/prompts/
```

For example, `~/.handsfree/prompts/conductor_system.md` overrides
`prompts/conductor_system.md`.
