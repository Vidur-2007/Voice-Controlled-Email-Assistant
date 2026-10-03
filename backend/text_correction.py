"""Mid-speech self-correction (F9) — "no wait, change that to…" is handled
as a revision rather than literal text.

A true live-audio interrupt is a frontend/STT-level concept this turn-based
architecture doesn't have — every turn's transcript is atomic, submitted
only after the browser's own end-of-turn debounce. So this is a
deterministic TEXT preprocessor, applied once to the whole raw transcript
before anything else touches it (routes/voice.py::_handle_turn, right
after the transcript is trimmed) — one hook point covers every phase
uniformly (idle composing, awaiting_confirm free-form edits, in-progress
reply content) instead of patching each call site separately.

Markers are deliberately multi-word and low-collision. A bare "actually"
was considered and rejected — it would destructively truncate legitimate
content like "I'm actually running late" (silently keeping only "running
late"). Even the chosen markers carry a residual, accepted risk: genuine
dictated content that happens to contain the same words with a different
meaning (e.g. really dictating "please wait, no wait for my reply") would
still get incorrectly truncated. This is the only implementable reading of
F9 in this architecture; the marker set is chosen to make real collisions
rare, not to eliminate them.
"""

import re

_MARKERS = ("no wait", "wait no", "sorry i mean", "i mean", "scratch that")

# Longest-first so "sorry i mean" is tried before the "i mean" it contains —
# otherwise the shorter marker would match first and leave "sorry" stuck
# onto the front of the kept remainder.
_PATTERN = re.compile(
    "|".join(re.escape(m) for m in sorted(_MARKERS, key=len, reverse=True)),
    re.IGNORECASE,
)


def strip_correction(transcript: str) -> str:
    """Keep only the text after the LAST correction marker's end. Returns
    the transcript unchanged if no marker is present. A marker with
    nothing after it (the whole utterance is just "scratch that") returns
    "" — the caller re-checks for an empty transcript after calling this.
    """
    last_end = None
    for match in _PATTERN.finditer(transcript):
        last_end = match.end()

    if last_end is None:
        return transcript

    return transcript[last_end:].strip(" ,.")
