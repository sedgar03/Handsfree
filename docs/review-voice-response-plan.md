# Review: Voice Response to AskUserQuestion Plan

**Reviewer:** Claude Sonnet 4.5
**Date:** 2026-02-16
**Plan:** `/Users/steven_edgar/.claude/plans/gleaming-napping-journal.md`

---

## Executive Summary

The plan proposes a clever state-file-based approach to enable voice responses to Claude Code's AskUserQuestion prompts. The user hears the question via TTS, speaks "option B" into their AirPods, and the listener simulates keyboard navigation to select the option. The core architecture is sound, but there are significant concerns around keyboard simulation reliability, Whisper transcription robustness, and several edge cases that need addressing.

**Verdict:** Approve with required modifications (detailed below).

---

## Strengths

### 1. Minimal State Coordination
The pending question file approach (`/tmp/handsfree-pending-question.json`) is elegant:
- Single source of truth for whether a question is active
- No new IPC mechanism needed
- Timestamp-based staleness prevents old questions from being answered
- Clean separation: hook writes, listener reads

### 2. Reuses Existing Recording Infrastructure
The plan correctly leverages the existing `media_key_listener.py` state machine rather than creating a parallel recording path. This avoids microphone conflicts and code duplication.

### 3. Graceful Degradation
Falls back to normal text injection when:
- No match is found for the spoken response
- The pending question file is stale (>5 minutes)
- The file doesn't exist

This means the feature won't break existing workflows.

### 4. TTS Confirmation Feedback
Speaking "Selected option B" after selection provides critical audio feedback for a hands-free user who can't see the screen.

---

## Concerns

### Critical Issues

#### 1. Keyboard Simulation Correctness (HIGH SEVERITY)

**The Problem:** The plan assumes arrow-down navigation works in Claude Code's AskUserQuestion picker. However:

- Claude Code's picker implementation details are not verified in the plan
- Terminal pickers vary: some use arrow keys, some use j/k, some use numbers
- The plan assumes the first option is pre-selected, but this needs verification
- macOS osascript keyboard simulation can be unreliable in terminal emulators

**Evidence from code:**
```python
# From plan - line 87-96
def _select_picker_option(index: int):
    script_parts = ['tell application "System Events"']
    for _ in range(index):
        script_parts.append('  key code 125')  # down arrow
        script_parts.append('  delay 0.05')
    script_parts.append('  delay 0.1')
    script_parts.append('  key code 36')  # Enter
```

This assumes:
- Arrow down (keycode 125) navigates the picker
- 0.05s delay is sufficient between keypresses
- The picker is still focused and hasn't been dismissed
- The frontmost application is the terminal running Claude Code

**Risk:** This could select the wrong option or fail silently if:
- The user switches windows between speaking and keyboard simulation
- The picker uses different navigation keys
- Terminal emulator key forwarding is flaky
- Timing is off and keypresses are dropped

**Required Test:** Before implementing, verify that:
1. Claude Code's AskUserQuestion uses arrow keys for navigation
2. The first option is pre-selected (index 0 requires 0 down arrows)
3. Keyboard simulation works reliably in iTerm2, Terminal.app, etc.

#### 2. Whisper Transcription Ambiguity (MEDIUM SEVERITY)

**The Problem:** The plan's parsing logic (line 62-76) handles basic cases but misses phonetically similar transcriptions:

| User says | Whisper might hear | Plan handles? |
|-----------|-------------------|---------------|
| "B" | "be", "bee", "me", "v" | No |
| "A" | "eh", "ay", "hey" | No |
| "first one" | "first 1", "1st one" | Partial |
| "cancel" | "cancel it", "counselor" | No |
| "Other" | "the other", "another" | Unclear |

The plan mentions "Option label text (fuzzy)" but doesn't define the fuzzy matching algorithm.

**Evidence from stt.py:**
```python
def transcribe(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
    whisper = _get_whisper()
    result = whisper.transcribe(
        audio,
        path_or_hf_repo=MODEL_ID,
        language="en",
    )
    return result.get("text", "").strip()
```

No preprocessing or normalization. Whisper-large-v3-turbo is good, but not perfect for single-letter utterances.

**Risk:** User says "B" but Whisper hears "be" → no match → falls back to text injection → "be" gets pasted into Claude Code → user has to manually delete it.

#### 3. Race Condition: Hook vs. Listener (MEDIUM SEVERITY)

**The Problem:** The hook is async (`async: true` in hook config), meaning:
1. Claude Code calls the hook and immediately continues
2. The hook runs in the background, speaks via TTS, writes the pending file
3. The user hears the question and immediately clicks their AirPod stem
4. The listener checks for the pending file

**Timing scenario:**
```
t=0ms:   Claude Code invokes ask_question_hook.py (async)
t=10ms:  Claude Code shows picker on screen
t=50ms:  Hook starts TTS ("Attention: there's a question...")
t=500ms: User clicks stem (heard TTS, doesn't wait for full question)
t=510ms: Listener checks /tmp/handsfree-pending-question.json → DOESN'T EXIST YET
t=600ms: Hook finishes TTS, writes pending file
```

The listener will fall back to text injection before the hook writes the file.

**Evidence from ask_question_hook.py:**
```python
# Line 80-112: speaks all questions, then at the end...
_log("Finished speaking question(s)")
# Plan says to write file here, but TTS is slow (2-5 seconds for full question)
```

The plan doesn't specify when the file is written. If it's after all TTS completes, the race window is 2-5 seconds.

#### 4. Multiple Questions Handling (LOW SEVERITY)

The plan says (line 122):
> "We write state for the last question's options."

But Claude Code's AskUserQuestion can present 1-4 questions sequentially. The picker shows them one at a time. If the hook writes only the last question's options, but the user is responding to the first question, the indices won't match.

**Example:**
```json
{
  "questions": [
    {"question": "Pick a color", "options": ["Red", "Blue"]},
    {"question": "Pick a size", "options": ["Small", "Medium", "Large"]}
  ]
}
```

Hook writes `{"options": ["Small", "Medium", "Large"]}` (last question).
User says "Red" (answering the first question, which is shown first).
Listener parses "Red" → no match in ["Small", "Medium", "Large"] → falls back to text injection.

**From ask_question_hook.py line 84-111:**
```python
for i, q in enumerate(questions):
    # speak question and options...
# Only writes file AFTER loop completes
```

The plan needs clarification: does it write state for each question as it's spoken, or only the last one after all questions finish?

---

### Design Issues

#### 5. No Timeout on Keyboard Simulation

The `_select_picker_option()` function has fixed delays (0.05s per arrow, 0.1s before Enter). If the picker is slow to render or update, keypresses arrive too early and are dropped.

Better approach: add a timeout and retry mechanism, or use a longer initial delay.

#### 6. No Validation of Option Index

What if the parsed option index is out of bounds? The plan doesn't check if `index >= len(options)`. Pressing arrow-down 10 times when there are only 3 options might wrap around or cause undefined behavior.

#### 7. No Handling of "Other" Option Behavior

The plan mentions (line 123):
> "Other" option: Navigate to it (index = len(options)), press Enter. The picker then shows a text input.

But if "Other" is selected and the picker switches to a text input, the next stem-click should NOT check for a pending question (since it's now a text input, not a picker). The plan doesn't clear the pending file or update state to reflect this.

---

## Edge Cases Missed

### 1. User Speaks Before TTS Finishes
User clicks stem while the hook is still speaking options. Listener records their response, but they might have only heard "Option A" and said "A" without hearing the full question. This is acceptable (user's responsibility), but worth noting in docs.

### 2. User Cancels Recording
If the user triple-clicks to cancel recording (line 483-488 in media_key_listener.py), the pending question file is not cleared. Next stem-click will still try to answer the old question.

**Solution:** Clear the pending file in `_cancel_recording()`.

### 3. Pending File Persists Across Multiple Questions
If the user answers one question, the file is cleared. But if they don't answer (walk away), the file sits there for 5 minutes. If Claude Code asks another question in that window, the old file is still present with stale options.

**Mitigation:** The timestamp check (300s expiry) helps, but a per-question unique ID would be more robust. Hook could write `{"id": <timestamp>, "options": [...]}` and listener checks if the ID matches the current active picker.

### 4. Listener Not Running
Plan mentions (line 121): "The pending file sits there; user clicks option manually. No harm."

True, but the file is never cleaned up. After many questions, `/tmp` accumulates stale files.

**Solution:** Hook could delete any existing pending file before writing a new one, or use a fixed filename (already the case: `/tmp/handsfree-pending-question.json`).

### 5. User Speaks an Option That's Also Valid Text
User says "Dispatch now" which is both:
- A valid response to the question "Ready to dispatch?"
- Potentially valid text input if there's no pending question

If the listener matches "Dispatch now" to an option label, it selects the option. But if the match is fuzzy and wrong, it might select the wrong option instead of pasting text.

**Risk Level:** Medium — fuzzy matching on full labels is powerful but dangerous.

---

## Suggestions

### High Priority

1. **Add pre-implementation verification:**
   ```bash
   # Test keyboard simulation manually
   osascript -e 'tell application "System Events" to key code 125'
   # Verify it moves cursor in Claude Code's picker
   ```

2. **Write pending file IMMEDIATELY after starting TTS, not after:**
   ```python
   # In ask_question_hook.py, move this BEFORE speak():
   state = {"options": [...], "timestamp": time.time()}
   with open(PENDING_QUESTION_FILE, "w") as f:
       json.dump(state, f)

   # Then speak
   speak("Attention: there's a question...")
   ```
   This closes the race window to <100ms.

3. **Improve Whisper parsing with phonetic aliases:**
   ```python
   PHONETIC_ALIASES = {
       "be": "B", "bee": "B", "v": "B",
       "eh": "A", "ay": "A", "hey": "A",
       "sea": "C", "see": "C",
       "dee": "D", "d": "D",
   }

   def _parse_option(text: str, options: list[str]) -> int | None:
       text_lower = text.lower().strip()

       # Phonetic alias resolution
       if text_lower in PHONETIC_ALIASES:
           text_lower = PHONETIC_ALIASES[text_lower].lower()

       # Existing logic...
   ```

4. **Bounds check on option index:**
   ```python
   def _select_picker_option(index: int, num_options: int):
       if index < 0 or index >= num_options:
           print(f"[listener] Invalid index {index} for {num_options} options", file=sys.stderr)
           return
       # ... rest of function
   ```

5. **Clear pending file on recording cancel:**
   ```python
   # In media_key_listener.py _cancel_recording()
   def _cancel_recording(self):
       # ... existing code ...
       PENDING_QUESTION_FILE.unlink(missing_ok=True)
   ```

### Medium Priority

6. **Add per-question unique ID:**
   ```python
   # In hook:
   state = {
       "id": str(time.time()),  # or uuid.uuid4().hex
       "options": [...],
       "timestamp": time.time(),
   }

   # In listener:
   # Check if ID matches Claude Code's internal question ID (if accessible)
   # Or just use timestamp as a correlation ID
   ```

7. **Increase initial delay before keyboard sim:**
   ```python
   script_parts.append('  delay 0.3')  # Was 0.1
   script_parts.append('  key code 36')
   ```
   Terminal rendering can be slow, especially in tmux/remote sessions.

8. **Add debug mode that logs what was matched:**
   ```python
   _log(f"User said: '{text}' -> matched option {index}: '{options[index]}'")
   ```
   This helps diagnose mismatches.

### Low Priority

9. **Support voice commands to cancel:**
   ```python
   if text.lower() in ("cancel", "never mind", "go back"):
       PENDING_QUESTION_FILE.unlink(missing_ok=True)
       speak("Cancelled.")
       return True
   ```

10. **Retry keyboard simulation if it fails:**
    ```python
    for attempt in range(3):
        _select_picker_option(index)
        time.sleep(0.2)
        # Check if picker is still visible (heuristic: send ESC, see if it's dismissed)
        # If dismissed, success. Else retry.
    ```

---

## Architecture Assessment

### Is the State File Approach Clean?

**Yes, with caveats:**

**Pros:**
- Simple: just JSON read/write
- No new dependencies (no Redis, no sockets)
- Debuggable: `cat /tmp/handsfree-pending-question.json`
- Atomic writes on POSIX systems (though technically not guaranteed)

**Cons:**
- Doesn't scale to multiple concurrent questions (if Claude Code ever supports that)
- No way to detect if the picker is still visible (user could have dismissed it)
- File system state can get out of sync if process crashes

**Better alternatives:**
1. **Unix domain socket:** Hook opens a socket, listener connects. More complex but real-time.
2. **Named pipe (FIFO):** Blocking, simpler than socket. Hook writes, listener reads.
3. **macOS distributed notifications:** PyObjC can send/receive NSDistributedNotification. Zero file system footprint.

**Verdict:** The state file is fine for MVP. If you want more robustness, switch to distributed notifications.

---

## Missing from Plan

1. **No mention of cleanup on listener shutdown:** Should the listener delete the pending file in its finally block?
2. **No mention of logging:** The plan shows `_log()` in the hook but not in the listener's `_try_answer_question()`.
3. **No test plan:** The verification section (line 125-137) is manual. Consider adding a pytest test that mocks the state file and transcription.
4. **No accessibility fallback:** What if the user has a screen reader or other assistive tech that interferes with keyboard simulation?

---

## Recommendations Summary

| Priority | Recommendation | Effort |
|----------|---------------|--------|
| **CRITICAL** | Write pending file before TTS, not after | 5 min |
| **CRITICAL** | Verify keyboard navigation works in Claude Code picker | 15 min |
| **HIGH** | Add phonetic aliases for single-letter options | 30 min |
| **HIGH** | Bounds check option index before keyboard sim | 10 min |
| **HIGH** | Clear pending file in `_cancel_recording()` | 5 min |
| **MEDIUM** | Increase keyboard sim delay to 0.3s | 2 min |
| **MEDIUM** | Add debug logging for matches | 10 min |
| **LOW** | Support "cancel" voice command | 20 min |
| **LOW** | Add retry logic for keyboard simulation | 30 min |

**Total estimated effort for HIGH+CRITICAL items:** ~1 hour

---

## Verdict

**Approve with required modifications.**

The plan is architecturally sound and leverages existing infrastructure well. However, there are three critical issues that must be addressed before implementation:

1. **Keyboard simulation must be verified** against Claude Code's actual picker behavior
2. **Pending file must be written before TTS** to avoid race conditions
3. **Phonetic matching must be robust** for single-letter options

With these changes, the feature should work reliably for the 90% case. Edge cases (user switches windows, very long option lists, concurrent questions) can be addressed iteratively.

**Confidence Level:** Medium-High (75%)
**Biggest Unknown:** Keyboard simulation reliability across terminal emulators
**Biggest Risk:** Whisper transcription ambiguity for short utterances
