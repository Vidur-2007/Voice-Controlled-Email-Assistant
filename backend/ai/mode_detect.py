"""Automatic dictation-vs-brief mode detection (F3, F4, F5).

Heuristics first — most turns never reach the model at all, which keeps
the command grammar's "instant, predictable" promise (§16) extending into
composition too:
  explicit override phrase  -> decided, no model call
  under 15 words             -> brief, no model call
  over 40 words               -> dictation, no model call
  otherwise (15-40 words)      -> ask the model; ask the USER if it can't
                                  decide confidently either
"""

from dataclasses import dataclass
from typing import Optional

from backend.ai import prompts, provider
from backend.ai.schemas import ModeChoice
from backend.config import get_settings
from backend.speechify import word_count

Mode = str  # "dictation" | "brief"

ASK_MODE_QUESTION = "Do you want to dictate this word for word, or should I write it for you?"

_SHORT_WORD_LIMIT = 15
_LONG_WORD_LIMIT = 40
_CONFIDENCE_THRESHOLD = 0.6

_DICTATION_TRIGGERS = ("dictate this", "take this down", "write this down", "word for word")
_BRIEF_TRIGGERS = ("write it for me", "you write it", "compose it for me")

_DICTATION_ANSWERS = {"dictate it", "dictate", "word for word", "dictation", "take it down"}
_BRIEF_ANSWERS = {"write it for me", "you write it", "brief", "write it", "compose it"}


@dataclass
class DetectResult:
    ask: bool
    mode: Optional[Mode] = None


def check_override(transcript: str) -> Optional[tuple[Mode, str]]:
    """F4: an explicit trigger phrase forces a mode immediately, no
    heuristics or model call. Returns (mode, remainder) if the transcript
    starts with a trigger phrase, else None. `remainder` is "" if the
    trigger was said on its own (the content comes on the next turn).
    """
    low = transcript.strip().lower()

    for trigger in _DICTATION_TRIGGERS:
        remainder = _strip_prefix(transcript, low, trigger)
        if remainder is not None:
            return "dictation", remainder

    for trigger in _BRIEF_TRIGGERS:
        remainder = _strip_prefix(transcript, low, trigger)
        if remainder is not None:
            return "brief", remainder

    return None


def _strip_prefix(original: str, low: str, trigger: str) -> Optional[str]:
    if low == trigger:
        return ""
    prefix = trigger + " "
    if low.startswith(prefix):
        return original.strip()[len(prefix):].strip()
    return None


def detect_mode(transcript: str) -> DetectResult:
    """F3: heuristics first, model only for the genuinely ambiguous zone."""
    wc = word_count(transcript)

    if wc < _SHORT_WORD_LIMIT:
        return DetectResult(ask=False, mode="brief")
    if wc > _LONG_WORD_LIMIT:
        return DetectResult(ask=False, mode="dictation")

    settings = get_settings()
    if settings.fake_ai:
        # No fake model to consult for the ambiguous zone — default to
        # brief so the offline flow always stays a single round trip.
        return DetectResult(ask=False, mode="brief")

    # Any failure here (SpokenError) is intentionally NOT swallowed —
    # it propagates to the caller so the real problem (e.g. Ollama isn't
    # running) is spoken, rather than being masked behind a misleading
    # "which mode?" question that would just fail again on the next turn.
    choice = provider.generate(prompts.SYSTEM_MODE, transcript, ModeChoice)

    if choice.mode == "unclear" or choice.confidence < _CONFIDENCE_THRESHOLD:
        return DetectResult(ask=True)
    return DetectResult(ask=False, mode=choice.mode)


def match_mode_answer(transcript: str) -> Optional[Mode]:
    """Resolve the user's reply to ASK_MODE_QUESTION (F5)."""
    low = transcript.strip().lower()
    if low in _DICTATION_ANSWERS:
        return "dictation"
    if low in _BRIEF_ANSWERS:
        return "brief"
    return None
