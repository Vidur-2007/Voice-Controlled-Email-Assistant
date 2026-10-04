"""Text -> speakable text (rule A12), and the readback builder (F23, F26).

`build_readback()` lives here rather than in routes/voice.py so both the
turn orchestrator and (later) the inbox reader can share it, and so it is
unit-testable without spinning up FastAPI.
"""

import re
from pathlib import Path

from backend.models import ContactCandidate, Draft, InboxItem

_MARKDOWN_CHARS = re.compile(r"[*_`#>~\[\]]")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")
_REPEATED_PERIODS = re.compile(r"\.{2,}")
_WHITESPACE = re.compile(r"\s+")

_LONG_BODY_WORD_THRESHOLD = 120


def word_count(text: str) -> int:
    return len(text.split())


def speakable_email(address: str) -> str:
    """'john.smith@example.com' -> 'john dot smith at example dot com'."""
    if not address:
        return ""
    out = address.replace("@", " at ").replace(".", " dot ")
    return _WHITESPACE.sub(" ", out).strip()


def normalize_for_speech(text: str) -> str:
    """Strip markdown, spell out embedded addresses, turn paragraph breaks
    into audible pauses. Safe to call on empty text.
    """
    if not text:
        return ""
    t = text.replace("\r\n", "\n")
    t = _PARAGRAPH_BREAK.sub(". ", t)  # paragraph break -> pause
    t = t.replace("\n", " ")  # single line break -> space
    t = _MARKDOWN_CHARS.sub("", t)  # strip markdown punctuation
    t = _EMAIL_RE.sub(lambda m: speakable_email(m.group(0)), t)
    t = _REPEATED_PERIODS.sub(".", t)  # collapse doubled periods from pause insertion
    return _WHITESPACE.sub(" ", t).strip()


def _cc_names(draft: Draft) -> list[str]:
    """One speakable name per `draft.cc` entry — `draft.cc_names[i]` if
    present, else the address itself spelled out. Positional, not a dict,
    to mirror how cc/cc_names are appended in lockstep by whatever adds a
    CC (voice.py's ADD_CC handler).
    """
    names = []
    for i, email in enumerate(draft.cc):
        name = draft.cc_names[i] if i < len(draft.cc_names) else ""
        names.append(name or speakable_email(email))
    return names


def _join_plain_and(items: list[str]) -> str:
    """No comma at exactly 2 items ("Sarah and Alex"); Oxford comma at 3+,
    mirroring `_join_plain_or`'s comma rule but with "and" for CC lists.
    """
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _cc_speech(draft: Draft) -> str:
    """A6: who's being copied must be heard before send, the same way the
    recipient must be — never buried, never silent.
    """
    names = _cc_names(draft)
    if not names:
        return ""
    return f"Copying {_join_plain_and(names)}."


def _bcc_names(draft: Draft) -> list[str]:
    """Exact mirror of _cc_names() for draft.bcc/bcc_names."""
    names = []
    for i, email in enumerate(draft.bcc):
        name = draft.bcc_names[i] if i < len(draft.bcc_names) else ""
        names.append(name or speakable_email(email))
    return names


def _bcc_speech(draft: Draft) -> str:
    """A6: BCC is invisible to the OTHER recipients by definition, but the
    user sending it must still hear it before "send" is honoured — the
    rule doesn't get to skip a field just because it's normally hidden
    from everyone else.
    """
    names = _bcc_names(draft)
    if not names:
        return ""
    return f"Blind copying {_join_plain_and(names)}."


def _attachments_speech(draft: Draft) -> str:
    """A6/A12: an attachment changes what "send" actually does, so it must
    be heard before confirming, the same as CC.
    """
    if not draft.attachments:
        return ""
    names = [Path(p).name for p in draft.attachments]
    if len(names) == 1:
        return f"With one attachment: {names[0]}."
    return f"With {len(names)} attachments: {', '.join(names)}."


def build_readback(draft: Draft) -> str:
    """Recipient first, then CC, then BCC, then attachments, then subject,
    then body, then the confirmation prompt (F23). Mandatory before
    "send" can ever be honoured (A6).
    """
    recipient_speech = (
        draft.recipient_name or speakable_email(draft.recipient) or "an unspecified recipient"
    )
    subject_speech = normalize_for_speech(draft.subject) or "no subject"
    body_speech = normalize_for_speech(draft.body) or "an empty message"

    parts = [f"To {recipient_speech}."]

    cc_speech = _cc_speech(draft)
    if cc_speech:
        parts.append(cc_speech)

    bcc_speech = _bcc_speech(draft)
    if bcc_speech:
        parts.append(bcc_speech)

    attachments_speech = _attachments_speech(draft)
    if attachments_speech:
        parts.append(attachments_speech)

    parts.append(f"Subject: {subject_speech}.")
    parts.append("Message:")

    wc = word_count(draft.body)
    if wc > _LONG_BODY_WORD_THRESHOLD:
        parts.append(f"The message is about {wc} words. Here it is.")

    parts.append(body_speech)
    parts.append("Say send to send it, or tell me what to change.")
    return " ".join(parts)


def read_recipient(draft: Draft) -> str:
    """Spoken answer to "who is it going to" / "read the recipient" (F25)."""
    recipient_speech = (
        draft.recipient_name or speakable_email(draft.recipient) or "an unspecified recipient"
    )
    return f"This is going to {recipient_speech}."


def read_subject(draft: Draft) -> str:
    """Spoken answer to "read the subject" (F25)."""
    subject_speech = normalize_for_speech(draft.subject) or "no subject"
    return f"The subject is: {subject_speech}."


def read_body(draft: Draft) -> str:
    """Spoken answer to "read the body" (F25). Carries the same length
    warning as the full readback (F26), since the point of the warning is
    knowing how long to listen either way.
    """
    body_speech = normalize_for_speech(draft.body) or "an empty message"
    parts = []

    wc = word_count(draft.body)
    if wc > _LONG_BODY_WORD_THRESHOLD:
        parts.append(f"The message is about {wc} words. Here it is.")

    parts.append(body_speech)
    return " ".join(parts)


_ORDINAL_WORDS = ("one", "two", "three", "four", "five")


def _join_comma_or(items: list[str]) -> str:
    """Comma-before-'or', matching the spec's literal "Smith, or Carter" —
    used only at exactly 2 items in practice (F13 disambiguation names).
    """
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]}, or {items[1]}"
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def _join_plain_or(items: list[str]) -> str:
    """No comma at exactly 2 items (spec's literal "one or two"); Oxford
    comma at 3+ — the no-comma rule is scoped to N=2 only, not
    generalized, or 3+ ordinals would read as an ungrammatical run-on.
    """
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return ", ".join(items[:-1]) + f", or {items[-1]}"


def build_disambiguation_question(hint: str, candidates: list[ContactCandidate]) -> str:
    """F13: "Which John — Smith, or Carter? Say the last name, or say
    one or two." Always offers an ordinal as well as a name, because the
    user cannot read a list off the screen. Only ever called with 2+
    candidates (see resolve_recipient's 1-candidate rule) — a single
    candidate has nothing to disambiguate.
    """
    hint = hint.strip()
    hint_lower = hint.lower()

    labels = []
    for c in candidates:
        name_lower = c.name.lower()
        if hint_lower and hint_lower in name_lower:
            remainder = name_lower.replace(hint_lower, "", 1).strip()
            labels.append(remainder.title() if remainder else c.name)
        else:
            labels.append(c.name)

    distinguishing = _join_comma_or(labels)
    ordinals = _join_plain_or(list(_ORDINAL_WORDS[: len(candidates)]))

    return (
        f"Which {hint.title() or 'one'} — {distinguishing}? "
        f"Say the last name, or say {ordinals}."
    )


def summarize_draft(draft: Draft) -> str:
    """Short one-line summary for "Undone."/"Redone." (F31) — recipient and
    subject only, not the body, since this is meant to be brief.
    """
    recipient_speech = draft.recipient_name or speakable_email(draft.recipient) or "no one yet"
    subject_speech = normalize_for_speech(draft.subject) or "no subject"
    return f"To {recipient_speech}. Subject: {subject_speech}."


def describe_inbox_item(item: InboxItem) -> str:
    """Spoken description of a single inbox item — sender, subject, and a
    short preview (F38/F39). Reused for both the full listing and for
    "next email"/"previous email" navigation, so it never diverges.
    """
    sender_speech = item.sender_name or speakable_email(item.sender_email) or "someone"
    subject_speech = normalize_for_speech(item.subject) or "no subject"
    snippet_speech = normalize_for_speech(item.snippet)

    parts = [f"From {sender_speech}.", f"Subject: {subject_speech}."]
    if snippet_speech:
        parts.append(snippet_speech)
    return " ".join(parts)


def build_inbox_listing(items: list[InboxItem]) -> str:
    """Spoken response to "read my unread mail" (F38) — every unread item,
    numbered so the user can navigate to one by ordinal later if needed.
    """
    if not items:
        return "You have no unread mail."

    count_speech = "one unread message" if len(items) == 1 else f"{len(items)} unread messages"
    lines = [f"You have {count_speech}."]
    for i, item in enumerate(items, start=1):
        lines.append(f"Message {i}. {describe_inbox_item(item)}")
    lines.append("Say next email to move through them, or a command like summarise this one.")
    return " ".join(lines)


def build_full_message_readback(thread_text: str) -> str:
    """Spoken response to "read it in full" (F38) — the whole thread's
    text, with the same long-message word-count warning as build_readback
    (A11/A12): the point of the warning is knowing how long to listen.
    """
    text_speech = normalize_for_speech(thread_text) or "This message doesn't have any readable content."
    parts = []

    wc = word_count(thread_text)
    if wc > _LONG_BODY_WORD_THRESHOLD:
        parts.append(f"The message is about {wc} words. Here it is.")

    parts.append(text_speech)
    return " ".join(parts)


def speak_time_of_day(dt) -> str:
    """'17:00' -> '5 PM', '17:30' -> '5:30 PM' (F35). Deliberately not
    `strftime('%-I...')` — that raises `ValueError` on Windows (needs
    `%#I`), so the 12-hour value is computed by hand instead of relying on
    a platform-specific directive.
    """
    hour12 = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    if dt.minute:
        return f"{hour12}:{dt.minute:02d} {ampm}"
    return f"{hour12} {ampm}"


def speak_schedule_time(dt, rolled_to_tomorrow: bool = False, is_tomorrow: bool = False) -> str:
    """Spoken confirmation for a resolved schedule time (F35, A12) — never
    a raw ISO string. `rolled_to_tomorrow` means the time was in the past
    today and silently rolling forward would hide that from a user who
    can't see a calendar, so it's said out loud; `is_tomorrow` covers an
    explicit "tomorrow at ..." with no rollover involved.
    """
    time_speech = speak_time_of_day(dt)
    if rolled_to_tomorrow:
        return f"{time_speech} tomorrow, since {time_speech} today has already passed"
    if is_tomorrow:
        return f"{time_speech} tomorrow"
    return f"{time_speech} today"
