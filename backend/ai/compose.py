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
from typing import Literal

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


def compose_email(transcript: str, mode: Mode) -> tuple[Draft, str]:
    settings = get_settings()
    if settings.fake_ai:
        draft, recipient_hint = _fake_compose(transcript)
    else:
        draft, recipient_hint = _real_compose(transcript, mode)

    draft.body = _apply_paragraph_breaks(draft.body)
    return draft, recipient_hint


def _fake_compose(transcript: str) -> tuple[Draft, str]:
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

    draft = Draft(subject=subject, body=body, tone="neutral", length="normal")
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


def _real_compose(transcript: str, mode: Mode) -> tuple[Draft, str]:
    settings = get_settings()
    system = prompts.SYSTEM_DICTATE if mode == "dictation" else prompts.SYSTEM_COMPOSE

    sign_off = (
        f'Sign off with the name "{settings.user_first_name}" if it fits.'
        if settings.user_first_name
        else "Do not add any sign-off — no name was given."
    )
    user = f"Transcript: {transcript}\n\n{sign_off}"

    fields = provider.generate(system, user, DraftFields)

    draft = Draft(
        subject=(fields.subject.strip() or "Message")[:_SUBJECT_CHAR_LIMIT],
        body=fields.body.strip(),
        tone=fields.tone,
        length="normal",
    )
    return draft, fields.recipient_hint.strip()


def compose_reply(instruction: str, thread_context: str) -> Draft:
    """Phase 6 (F36/F41): fills in ONLY body/tone/length. Recipient,
    subject, thread_id, and in_reply_to are already set on the in-progress
    reply draft by routes/voice.py (from the inbox item being replied to)
    and must never be overwritten here — the caller merges this result's
    body/tone into that existing draft, keeping everything else as-is.
    """
    settings = get_settings()
    if settings.fake_ai:
        return _fake_compose_reply(instruction)
    return _real_compose_reply(instruction, thread_context)


def _fake_compose_reply(instruction: str) -> Draft:
    body_source = instruction.strip()
    body = _sentence_case(body_source) if body_source else ""
    return Draft(body=body, tone="neutral", length="normal")


def _real_compose_reply(instruction: str, thread_context: str) -> Draft:
    user = f"Original thread:\n{thread_context}\n\nReply instruction: {instruction}"
    # DraftFields is reused rather than a new schema — recipient_hint and
    # subject are simply discarded below, never assigned onto the result.
    fields = provider.generate(prompts.SYSTEM_REPLY, user, DraftFields)
    return Draft(body=fields.body.strip(), tone=fields.tone, length="normal")
