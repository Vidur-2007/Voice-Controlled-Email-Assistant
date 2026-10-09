"""Draft composition — the fake/real switch lives here (§5).

FAKE_AI=1 (default): a deterministic, transcript-derived draft with no
network call. Good enough to exercise the whole conversation flow offline.
The fake path deliberately ignores `mode` (see _fake_compose) — faking the
actual difference between verbatim dictation and AI-expanded brief mode
isn't feasible with simple string ops, and the existing heuristic already
approximates verbatim preservation reasonably.

FAKE_AI=0: real composition via a local Ollama model (structured output
through a JSON Schema, per §19a). `mode` picks SYSTEM_DICTATE vs
SYSTEM_COMPOSE.

Returns (draft, recipient_hint) rather than a fully-resolved Draft: the raw
spoken name ("john", "my manager") is kept separate from the resolved
recipient/recipient_name, which backend/data/contacts.py::resolve_recipient()
fills in (routes/voice.py calls it).
"""

import re
from typing import Literal, Optional

from backend.ai import prompts, provider
from backend.ai.schemas import DraftFields
from backend.config import get_settings
from backend.models import Draft

_TRIGGER_WORDS = ("tell", "email", "message")
_SUBJECT_WORD_LIMIT = 5
_SUBJECT_CHAR_LIMIT = 60

Mode = Literal["dictation", "brief"]

# F28: "new paragraph" (dictation mode) -> an actual paragraph break. A
# standalone _PHRASES entry would almost never fire mid-dictation (real
# dictation transcripts are much longer than two words), so the real fix
# is this substitution, applied once here after EITHER compose path
# returns — a safety net rather than relying solely on SYSTEM_DICTATE's
# prompt instruction, since a 3B local model's instruction-following on
# formatting directives is exactly the class of thing that flakes.
_NEW_PARAGRAPH_RE = re.compile(r"\bnew paragraph\b[,.]?\s*", re.IGNORECASE)


def _apply_paragraph_breaks(body: str) -> str:
    return _NEW_PARAGRAPH_RE.sub("\n\n", body).strip()


def extract_recipient_hint(transcript: str) -> str:
    """F59 (Phase 12) — the exact trigger-word/_split_hint heuristic
    _fake_compose() already uses internally, exposed standalone so
    routes/voice.py can try resolving a recipient BEFORE composing, with
    zero model call. Returns "" if no trigger word matches; the caller
    falls back to composing first, exactly as before.
    """
    words = transcript.strip().split()
    if not words:
        return ""
    first = words[0].lower()
    if first in _TRIGGER_WORDS:
        hint, _rest = _split_hint(words[1:])
        return hint
    if first == "write" and len(words) > 1 and words[1].lower() == "to":
        hint, _rest = _split_hint(words[2:])
        return hint
    return ""


def compose_email(transcript: str, mode: Mode, tone_hint: Optional[str] = None) -> tuple[Draft, str]:
    settings = get_settings()
    if settings.fake_ai:
        draft, recipient_hint = _fake_compose(transcript, tone_hint)
    else:
        draft, recipient_hint = _real_compose(transcript, mode, tone_hint)

    draft.body = _apply_paragraph_breaks(draft.body)
    return draft, recipient_hint


def _fake_compose(transcript: str, tone_hint: Optional[str] = None) -> tuple[Draft, str]:
    words = transcript.strip().split()
    recipient_hint = ""
    body_words = words

    if words:
        first = words[0].lower()
        if first in _TRIGGER_WORDS:
            rest = words[1:]
            recipient_hint, body_words = _split_hint(rest)
        elif first == "write" and len(words) > 1 and words[1].lower() == "to":
            rest = words[2:]
            recipient_hint, body_words = _split_hint(rest)
        # else: no trigger word — treat the whole transcript as the body

    # No fallback to the whole transcript here: if the hint swallowed
    # everything (e.g. "email the whole team"), the body is genuinely
    # empty, not the trigger word + hint re-included verbatim as a body.
    body_source = " ".join(body_words).strip()
    body = _sentence_case(body_source) if body_source else ""

    subject_source = body_words or words
    subject = _build_subject(subject_source)

    draft = Draft(subject=subject, body=body, tone=tone_hint or "neutral", length="normal")
    return draft, recipient_hint


_POSSESSIVE_WORDS = ("my", "our")
_GROUP_ARTICLE = "the"
_GROUP_QUALIFIERS = ("whole", "entire")


def _split_hint(rest: list[str]) -> tuple[str, list[str]]:
    """Extract the recipient hint, which may be more than one word:
    "my manager" (relationship alias, F14), "the whole team" (group,
    F15), or "John Smith" (a full name — recognized only when BOTH words
    are capitalized, so ordinary lowercase connective words elsewhere in
    a transcript, e.g. "tell john that I will be late", never get
    mistaken for a second hint word).
    """
    if not rest:
        return "", []

    first = rest[0].strip(",.")
    first_lower = first.lower()

    if first_lower in _POSSESSIVE_WORDS and len(rest) > 1:
        second = rest[1].strip(",.")
        return f"{first} {second}", rest[2:]

    if first_lower == _GROUP_ARTICLE and len(rest) > 1:
        second = rest[1].strip(",.")
        if second.lower() in _GROUP_QUALIFIERS and len(rest) > 2:
            third = rest[2].strip(",.")
            return f"{first} {second} {third}", rest[3:]
        return f"{first} {second}", rest[2:]

    if len(rest) > 1:
        second = rest[1].strip(",.")
        if first[:1].isupper() and second[:1].isupper():
            return f"{first} {second}", rest[2:]

    return first, rest[1:]


def _sentence_case(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def _build_subject(words: list[str]) -> str:
    subject_words = words[:_SUBJECT_WORD_LIMIT]
    subject = " ".join(w.strip(",.") for w in subject_words).title()
    return (subject or "Message")[:_SUBJECT_CHAR_LIMIT]


def _real_compose(transcript: str, mode: Mode, tone_hint: Optional[str] = None) -> tuple[Draft, str]:
    settings = get_settings()
    system = prompts.SYSTEM_DICTATE if mode == "dictation" else prompts.SYSTEM_COMPOSE

    sign_off = (
        f'Sign off with the name "{settings.user_first_name}" if it fits.'
        if settings.user_first_name
        else "Do not add any sign-off — no name was given."
    )
    user = f"Transcript: {transcript}\n\n{sign_off}"
    if tone_hint:
        # F59 (Phase 12): mirrors _real_compose_reply's identical pattern —
        # a fresh compose's recipient can now be resolved before this call,
        # so the learned tone can finally reach the prompt, not just be
        # patched onto the field afterward.
        user += f"\n\nMatch this tone, since the user usually writes to this person this way: {tone_hint}."

    fields = provider.generate(system, user, DraftFields)

    draft = Draft(
        subject=(fields.subject.strip() or "Message")[:_SUBJECT_CHAR_LIMIT],
        body=fields.body.strip(),
        tone=tone_hint or fields.tone,
        length="normal",
    )
    return draft, fields.recipient_hint.strip()


def compose_reply(instruction: str, thread_context: str, tone_hint: Optional[str] = None) -> Draft:
    """Phase 6 (F36/F41): fills in ONLY body/tone/length. Recipient,
    subject, thread_id, and in_reply_to are already set on the in-progress
    reply draft by routes/voice.py (from the inbox item being replied to)
    and must never be overwritten here — the caller merges this result's
    body/tone into that existing draft, keeping everything else as-is.

    `tone_hint` is F42 (Phase 8) — a learned per-recipient tone from
    `backend.data.prefs.get_tone_for_recipient()`. Unlike a fresh compose
    (where the recipient isn't known until after composing, so F42 can
    only override the Draft.tone field afterward), a reply's recipient IS
    already known before this runs, so the hint can genuinely influence
    the generated wording — honoured in both the fake and real paths, so
    it's verifiable offline, not just a real-mode-only effect.
    """
    settings = get_settings()
    if settings.fake_ai:
        return _fake_compose_reply(instruction, tone_hint)
    return _real_compose_reply(instruction, thread_context, tone_hint)


def _fake_compose_reply(instruction: str, tone_hint: Optional[str]) -> Draft:
    body_source = instruction.strip()
    body = _sentence_case(body_source) if body_source else ""
    return Draft(body=body, tone=tone_hint or "neutral", length="normal")


def _real_compose_reply(instruction: str, thread_context: str, tone_hint: Optional[str]) -> Draft:
    user = f"Original thread:\n{thread_context}\n\nReply instruction: {instruction}"
    if tone_hint:
        user += f"\n\nMatch this tone, since the user usually writes to this person this way: {tone_hint}."
    # DraftFields is reused rather than a new schema — recipient_hint and
    # subject are simply discarded below, never assigned onto the result.
    fields = provider.generate(prompts.SYSTEM_REPLY, user, DraftFields)
    # Forced, not just requested, when a hint exists — the same "command
    # grammar decides WHICH edit, the model only rewords" philosophy
    # FORCED_TONE already uses elsewhere in this codebase, so Draft.tone
    # reliably reflects the applied default even if the model's own
    # report drifts.
    tone = tone_hint or fields.tone
    return Draft(body=fields.body.strip(), tone=tone, length="normal")
