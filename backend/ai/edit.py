"""Conversational editing (F27) and the grammar-matched tone/length
commands (F20/F21) — one shared entry point regardless of which triggered
it. voice.py force-sets tone/length on the returned Draft for the canned
commands specifically; free-form instructions keep whatever this returns.
"""

from backend.ai import prompts, provider
from backend.ai.schemas import DraftFields
from backend.config import get_settings
from backend.models import Draft

_SUBJECT_CHAR_LIMIT = 60

# Keyword -> tone, checked in order against the (lowercased) instruction.
_TONE_KEYWORDS = (
    ("formal", "formal"),
    ("friendly", "friendly"),
    ("firm", "firm"),
    ("apologetic", "apologetic"),
    ("polite", "apologetic"),
    ("sorry", "apologetic"),
)


def revise(draft: Draft, instruction: str) -> Draft:
    settings = get_settings()
    if settings.fake_ai:
        return _fake_revise(draft, instruction)
    return _real_revise(draft, instruction)


def _fake_revise(draft: Draft, instruction: str) -> Draft:
    """Deterministic, keyword-based stand-in — real semantic rewriting
    isn't fakeable, but this is enough to prove the plumbing and satisfy
    "a changed draft" for the tone/length commands the gate exercises.
    """
    low = instruction.lower()
    new_draft = draft.model_copy(deep=True)

    for keyword, tone in _TONE_KEYWORDS:
        if keyword in low:
            new_draft.tone = tone
            return new_draft

    if "shorter" in low or "short" in low:
        new_draft.body = _shorten(new_draft.body)
        return new_draft

    if "longer" in low or "detail" in low:
        new_draft.body = (new_draft.body.rstrip() + " I'll follow up with more detail if needed.").strip()
        return new_draft

    # A free-form instruction we can't meaningfully fake: no-op.
    return new_draft


def _shorten(body: str) -> str:
    """Word-halving, not first-sentence truncation — a single-sentence
    body (the common case from the fake composer) would otherwise be a
    no-op, silently failing to demonstrate the "shorter" command at all.
    """
    words = body.rstrip(".!?").split()
    if len(words) <= 1:
        return body
    half = max(1, len(words) // 2)
    return " ".join(words[:half]) + "."


def _real_revise(draft: Draft, instruction: str) -> Draft:
    user = (
        f"Current subject: {draft.subject}\n"
        f"Current body: {draft.body}\n\n"
        f"Instruction: {instruction}"
    )
    fields = provider.generate(prompts.SYSTEM_EDIT, user, DraftFields)

    new_draft = draft.model_copy(deep=True)
    new_draft.subject = (fields.subject.strip() or draft.subject)[:_SUBJECT_CHAR_LIMIT]
    new_draft.body = fields.body.strip() or draft.body
    new_draft.tone = fields.tone
    return new_draft
