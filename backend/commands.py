"""Deterministic command grammar (§22) — matched before any model call.

Phase 1 implemented SEND, CANCEL, HELP, RESTART, REPEAT. Phase 2 added the
partial-review commands (F25): READ_SUBJECT, READ_BODY, READ_RECIPIENT.
Phase 3 added UNDO/REDO (F31) and the tone/length editing commands
(F20/F21) — these decide WHICH edit deterministically; only the actual
rewording (in backend/ai/edit.py) touches the model. Phase 5 adds
SAVE_DRAFT (F34) and RECONNECT (voice-side of reconnecting Gmail — see
backend/gmail/auth.py's module docstring for why this is informational
only, not an inline action). Phase 6 adds inbox navigation/reading
(READ_INBOX, NEXT_EMAIL, PREV_EMAIL, READ_SENDER, ARCHIVE, SUMMARISE —
§22's given phrases) plus READ_FULL, REPLY, and MARK_READ, three phrase
sets §22 doesn't give explicit wording for (flagged the same way earlier
phases flagged similar grammar gaps).

Phase 7 adds ADD_CC, NEW_PARAGRAPH, ATTACH, SCHEDULE (§22's given
phrases) plus ATTACH_LAST (a second Intent for "attach the last document
I mentioned" — §22 groups it under the same ATTACH phrase list, but
`_handle_command` never sees the raw transcript, so two behaviourally
different phrases need two Intent values, same as every other
synonym-cluster in this table). CC and schedule carry free-form content
(a name, a time) that can never be a literal `_PHRASES` key — see
`match_cc_trigger`/`match_schedule_trigger` below, which mirror the
prefix-matching `mode_detect.py::check_override()` already uses for F4.

Completeness pass (post-Phase-9 audit against the spec) adds: ADD_BCC
(F29 — "Add CC / BCC by voice" named BCC in its title but only CC was
ever wired; `match_bcc_trigger` mirrors `match_cc_trigger` exactly),
KEEP_GOING (§22 lists it explicitly — the phrase the app itself tells
users to say after an F10 auto-stop — but it was never actually
registered, so saying it risked leaking into compose/edit content as
literal text), and REPLY_ALL/FORWARD (F36 — "Reply / reply-all /
forward"; only plain reply was built in Phase 6, explicitly deferred at
the time; phrases invented the same way REPLY/READ_FULL/MARK_READ
already were).

Matching is exact-phrase (trimmed, lowercased, compared against the whole
transcript) — not substring search — so "I'll cancel my subscription"
doesn't accidentally trigger CANCEL.
"""

import re
from typing import Literal, Optional

from rapidfuzz import fuzz

from backend.models import Phase

# Bug fix (reported live): parse_command() did an exact dict lookup with
# no tolerance for a trailing period/comma Chrome's SpeechRecognition
# commonly appends at the end of a finalized utterance — "read my unread
# mail." silently missed every _PHRASES entry. Stripped before lookup,
# never before matching free-form trigger prefixes (match_cc_trigger
# etc.), which only care about a leading match.
_TRAILING_PUNCT_RE = re.compile(r"[.,!?]+$")

_CC_TRIGGERS = ("add cc ", "copy in ", "cc ", "copy ")
_BCC_TRIGGERS = ("add bcc ", "bcc ")
_SCHEDULE_TRIGGERS = ("send this at ", "send this for ", "schedule this for ", "schedule this at ")
# F55 (Phase 13) — longest-first so "search for the message" is tried
# before the bare "search for" it starts with; otherwise the shorter
# trigger would match first and leave "the message " stuck onto the
# front of the extracted query text.
_SEARCH_TRIGGERS = (
    "search for the message ",
    "search my email for ",
    "find the email ",
    "find an email ",
    "search for ",
)
# Bug fix: "change recipient" needs to survive ASR mis-hearing the word
# "recipient" itself (observed live: "change receipetant to ..."). An
# exact-phrase trigger can't do that — see match_change_recipient()'s
# fuzzy match against these synonyms instead.
_CHANGE_TARGET_SYNONYMS = ("recipient", "email", "address")
_CHANGE_TARGET_FUZZY_THRESHOLD = 65

Intent = Literal[
    "SEND",
    "CANCEL",
    "HELP",
    "RESTART",
    "REPEAT",
    "READ_SUBJECT",
    "READ_BODY",
    "READ_RECIPIENT",
    "UNDO",
    "REDO",
    "TONE_FORMAL",
    "TONE_FRIENDLY",
    "TONE_FIRM",
    "TONE_APOLOGETIC",
    "SHORTER",
    "LONGER",
    "SAVE_DRAFT",
    "RECONNECT",
    "READ_INBOX",
    "NEXT_EMAIL",
    "PREV_EMAIL",
    "READ_SENDER",
    "ARCHIVE",
    "SUMMARISE",
    "READ_FULL",
    "REPLY",
    "MARK_READ",
    "ADD_CC",
    "NEW_PARAGRAPH",
    "ATTACH",
    "ATTACH_LAST",
    "SCHEDULE",
    "ADD_BCC",
    "KEEP_GOING",
    "REPLY_ALL",
    "FORWARD",
    "SPELL_LAST",
    "SPELL_RECIPIENT",
    "SPELL_SUBJECT",
    "RESUME_DRAFT",
    "USE_SIGNOFF",
    "READ_ATTACHMENT",
    "READ_DRAFTS",
    "NEXT_DRAFT",
    "PREV_DRAFT",
    "SEND_DRAFT",
]

_PHRASES: dict[str, Intent] = {
    # SEND
    "send": "SEND",
    "send it": "SEND",
    "send it now": "SEND",
    "yes send": "SEND",
    "go ahead and send": "SEND",
    # CANCEL
    "cancel": "CANCEL",
    "never mind": "CANCEL",
    "forget it": "CANCEL",
    "discard": "CANCEL",
    # HELP
    "help": "HELP",
    "what can i say": "HELP",
    "what are my options": "HELP",
    # RESTART
    "start over": "RESTART",
    "scrap that": "RESTART",
    "start again": "RESTART",
    # REPEAT
    "repeat that": "REPEAT",
    "say that again": "REPEAT",
    "read it again": "REPEAT",
    "read it back": "REPEAT",
    # READ_SUBJECT (F25)
    "read the subject": "READ_SUBJECT",
    "what's the subject": "READ_SUBJECT",
    "whats the subject": "READ_SUBJECT",
    # READ_BODY (F25)
    "read the body": "READ_BODY",
    "read the message": "READ_BODY",
    # READ_RECIPIENT (F25)
    "who is it going to": "READ_RECIPIENT",
    "read the recipient": "READ_RECIPIENT",
    # UNDO / REDO (F31)
    "undo": "UNDO",
    "undo that": "UNDO",
    "redo": "REDO",
    "redo that": "REDO",
    # TONE (F20) — §22's table and F20's own phrase list differ slightly
    # for the apologetic case ("make it more polite" vs "make it
    # apologetic"); both are accepted per "accept all listed synonyms".
    "make it formal": "TONE_FORMAL",
    "make it friendly": "TONE_FRIENDLY",
    "make it firm": "TONE_FIRM",
    "make it more polite": "TONE_APOLOGETIC",
    "make it apologetic": "TONE_APOLOGETIC",
    # LENGTH (F21)
    "make it shorter": "SHORTER",
    "keep it short": "SHORTER",
    "add more detail": "LONGER",
    # SAVE_DRAFT (F34)
    "save as draft": "SAVE_DRAFT",
    "save it for later": "SAVE_DRAFT",
    # RECONNECT
    "reconnect my email": "RECONNECT",
    # READ_INBOX (F38, §22)
    "read my unread mail": "READ_INBOX",
    "read my unread mails": "READ_INBOX",
    "read my unread emails": "READ_INBOX",
    "check my email": "READ_INBOX",
    "check my emails": "READ_INBOX",
    "check my mail": "READ_INBOX",
    "check my mails": "READ_INBOX",
    # NEXT_EMAIL / PREV_EMAIL (F39, §22)
    "next email": "NEXT_EMAIL",
    "next message": "NEXT_EMAIL",
    "previous email": "PREV_EMAIL",
    "previous message": "PREV_EMAIL",
    # READ_SENDER (§22)
    "who is it from": "READ_SENDER",
    "read the sender": "READ_SENDER",
    # ARCHIVE (F40, §22)
    "archive this": "ARCHIVE",
    "archive it": "ARCHIVE",
    # SUMMARISE (F38, §22)
    "summarise this one": "SUMMARISE",
    "summarize this one": "SUMMARISE",
    "give me the gist": "SUMMARISE",
    # READ_FULL — not in §22's table; invented, flagged per the spec's own
    # rule for filling grammar gaps.
    "read it in full": "READ_FULL",
    "read the whole thing": "READ_FULL",
    "read the full message": "READ_FULL",
    # REPLY (F36) — not in §22's table; invented.
    "reply": "REPLY",
    "reply to this": "REPLY",
    "reply to this email": "REPLY",
    # MARK_READ (F40 names it explicitly; not in §22's table) — invented.
    "mark as read": "MARK_READ",
    "mark it as read": "MARK_READ",
    # ADD_CC (F29, §22) — the bare, content-free form. "add cc Sarah" /
    # "copy in Sarah" carry a name and are matched by match_cc_trigger()
    # below instead, never as a literal dict key.
    "add cc": "ADD_CC",
    # NEW_PARAGRAPH (F28, §22) — "dictation mode only" per the spec, and in
    # practice almost never arrives as its own whole turn (real dictation
    # transcripts are much longer); the real formatting effect is a text
    # substitution inside ai/compose.py. Kept here for §22 compliance, and
    # given real (not dead) behaviour in awaiting_confirm — see voice.py.
    "new paragraph": "NEW_PARAGRAPH",
    # ATTACH / ATTACH_LAST (F30, §22) — two Intents for the two listed
    # phrases; see the module docstring for why.
    "attach a file": "ATTACH",
    "attach a document": "ATTACH",
    "attach the last document i mentioned": "ATTACH_LAST",
    "attach that again": "ATTACH_LAST",
    # ADD_BCC (F29) — exact mirror of ADD_CC's bare form. "add bcc Sarah" /
    # "bcc Sarah" carry a name and are matched by match_bcc_trigger()
    # below instead, never as a literal dict key.
    "add bcc": "ADD_BCC",
    # KEEP_GOING (F10, §22) — the exact phrase the app itself tells users
    # to say after an auto-stop. Was never registered; saying it risked
    # falling through and being treated as literal compose/edit content.
    "keep going": "KEEP_GOING",
    # REPLY_ALL / FORWARD (F36) — not in §22's table; invented, same as
    # REPLY/READ_FULL/MARK_READ already were.
    "reply all": "REPLY_ALL",
    "reply to everyone": "REPLY_ALL",
    "reply all to this": "REPLY_ALL",
    "forward this": "FORWARD",
    "forward this email": "FORWARD",
    "forward it": "FORWARD",
    # SPELL (F52, Phase 11) — "spell that" repeats whichever field was
    # last discussed (ConversationState.last_field_named); the other two
    # name a specific field explicitly.
    "spell that": "SPELL_LAST",
    "spell it": "SPELL_LAST",
    "spell the recipient": "SPELL_RECIPIENT",
    "spell the subject": "SPELL_SUBJECT",
    # RESUME_DRAFT (F56, Phase 13) — "discard" already maps to CANCEL
    # above; only "resume" needs a new entry.
    "resume": "RESUME_DRAFT",
    # USE_SIGNOFF (F58, Phase 13)
    "use my usual sign-off": "USE_SIGNOFF",
    "use my usual signoff": "USE_SIGNOFF",
    # READ_ATTACHMENT (F57, Phase 13)
    "read the attachment": "READ_ATTACHMENT",
    "what's in the attachment": "READ_ATTACHMENT",
    "whats in the attachment": "READ_ATTACHMENT",
    # READ_DRAFTS / NEXT_DRAFT / PREV_DRAFT (Phase 15) — browsing
    # previously saved Gmail drafts, exact mirror of READ_INBOX/
    # NEXT_EMAIL/PREV_EMAIL. "send"/"send it" (already SEND above) is
    # reused for "send the draft I'm currently on" instead of a new
    # phrase — see voice.py's phase-aware SEND handling.
    "read my drafts": "READ_DRAFTS",
    "read my saved drafts": "READ_DRAFTS",
    "check my drafts": "READ_DRAFTS",
    "check my saved drafts": "READ_DRAFTS",
    "next draft": "NEXT_DRAFT",
    "previous draft": "PREV_DRAFT",
    # SEND_DRAFT (Phase 15) — a direct shortcut that works from anywhere,
    # without first saying "read my drafts": sends outright if there's
    # exactly one saved draft, otherwise asks the user to browse first
    # (see voice.py) rather than guessing which one was meant.
    "send my saved draft": "SEND_DRAFT",
    "send my draft": "SEND_DRAFT",
    "send the draft": "SEND_DRAFT",
    "send this draft": "SEND_DRAFT",
    # "change recipient" (bare or "... to X") is matched by
    # match_change_recipient() instead, as a free-form trigger — it
    # needs to tolerate ASR mis-hearing "recipient" itself, which a
    # literal _PHRASES entry can't do. See that function's docstring.
}

# Canned instructions passed to ai/edit.py::revise() for each grammar-
# matched tone/length command — the model only rewords, it never decides
# which edit to make.
EDIT_INSTRUCTIONS: dict[Intent, str] = {
    "TONE_FORMAL": "Rewrite the email in a more formal tone. Keep the same length and facts.",
    "TONE_FRIENDLY": "Rewrite the email in a warmer, friendly tone. Keep the same length and facts.",
    "TONE_FIRM": "Rewrite the email in a firmer, more assertive tone. Keep the same length and facts.",
    "TONE_APOLOGETIC": "Rewrite the email in a more apologetic tone. Keep the same length and facts.",
    "SHORTER": "Make the email noticeably shorter while keeping the key facts.",
    "LONGER": "Add a bit more detail to the email while keeping it natural.",
}

# What each canned edit command forces onto the resulting Draft, regardless
# of what the model itself reports (§ "command grammar decides WHICH edit").
FORCED_TONE: dict[Intent, str] = {
    "TONE_FORMAL": "formal",
    "TONE_FRIENDLY": "friendly",
    "TONE_FIRM": "firm",
    "TONE_APOLOGETIC": "apologetic",
}
FORCED_LENGTH: dict[Intent, str] = {
    "SHORTER": "short",
    "LONGER": "detailed",
}


def parse_command(transcript: str) -> Optional[Intent]:
    """Return the matched intent, or None if this falls through to
    language processing / phase-specific handling.
    """
    cleaned = _TRAILING_PUNCT_RE.sub("", transcript.strip()).strip().lower()
    return _PHRASES.get(cleaned)


def match_cc_trigger(transcript: str) -> Optional[str]:
    """F29: "copy in Sarah" / "add cc Sarah" — the name varies per
    utterance, so it can never be a literal `_PHRASES` key. Mirrors
    `mode_detect.py::check_override()`'s prefix-matching. Returns the
    trailing hint text, or None if no trigger prefix matched (including
    the bare "add cc" with nothing after it — that's `_PHRASES`' job).
    """
    stripped = transcript.strip()
    low = stripped.lower()
    for trigger in _CC_TRIGGERS:
        if low.startswith(trigger):
            hint = stripped[len(trigger):].strip()
            if hint:
                return hint
    return None


def match_bcc_trigger(transcript: str) -> Optional[str]:
    """F29: "bcc Sarah" / "add bcc Sarah" — exact mirror of
    match_cc_trigger(). Confirmed no collision either direction: "bcc "
    never starts with any of _CC_TRIGGERS' four prefixes, and "cc "/"copy"
    never start with either of _BCC_TRIGGERS' two.
    """
    stripped = transcript.strip()
    low = stripped.lower()
    for trigger in _BCC_TRIGGERS:
        if low.startswith(trigger):
            hint = stripped[len(trigger):].strip()
            if hint:
                return hint
    return None


def match_schedule_trigger(transcript: str) -> Optional[str]:
    """F35: "send this at 5pm" / "schedule this for tomorrow at 9am" — the
    time phrase varies per utterance. Returns the trailing time phrase, or
    None if no trigger prefix matched.
    """
    stripped = transcript.strip()
    low = stripped.lower()
    for trigger in _SCHEDULE_TRIGGERS:
        if low.startswith(trigger):
            phrase = stripped[len(trigger):].strip()
            if phrase:
                return phrase
    return None


def match_search_trigger(transcript: str) -> Optional[str]:
    """F55 (Phase 13): "find the email from Priya about the invoice" /
    "search for the message about the timetable" — the search content
    varies per utterance, so it can never be a literal `_PHRASES` key.
    Returns the trailing free text, or None if no trigger prefix matched.
    """
    stripped = transcript.strip()
    low = stripped.lower()
    for trigger in _SEARCH_TRIGGERS:
        if low.startswith(trigger):
            query = stripped[len(trigger):].strip()
            if query:
                return query
    return None


def match_change_recipient(transcript: str) -> Optional[str]:
    """Bug fix: "change recipient"/"change the recipient to X" needs to
    survive ASR mis-hearing the word "recipient" itself — observed live,
    twice: "change receipetant to bandaru weather@gmail.com". An exact
    phrase (or exact-phrase prefix) can't tolerate that at all, so this
    matches STRUCTURALLY ("change <word(s)> [to <value>]") and only
    requires the target word(s) to be *close* to "recipient"/"email"/
    "address" (fuzzy, not exact) — catches "receipetant", "recipiant",
    "recipitant", etc. without needing to enumerate every misheard
    variant, while still correctly rejecting unrelated edits like
    "change the tone to formal" (verified: "tone" scores nowhere near
    any of the three synonyms).

    Returns "" if matched with nothing after "to" (or no "to" at all —
    bare "change recipient"), the new value if one was given, or None
    if this isn't a change-recipient utterance at all.
    """
    words = transcript.strip().split()
    if len(words) < 2 or words[0].lower() != "change":
        return None
    lower_words = [w.lower().strip(",.") for w in words]

    if "to" in lower_words[1:]:
        to_index = lower_words.index("to", 1)
        target_words = [w for w in lower_words[1:to_index] if w != "the"]
        new_value = " ".join(words[to_index + 1 :]).strip()
    else:
        target_words = [w for w in lower_words[1:] if w != "the"]
        new_value = ""

    if not target_words:
        return None
    target_phrase = " ".join(target_words)
    matches_target = any(
        fuzz.ratio(target_phrase, syn) >= _CHANGE_TARGET_FUZZY_THRESHOLD
        or any(fuzz.ratio(w, syn) >= _CHANGE_TARGET_FUZZY_THRESHOLD for w in target_words)
        for syn in _CHANGE_TARGET_SYNONYMS
    )
    return new_value if matches_target else None


# Bug fix: "reply" and "reply all" were only ever registered as bare
# phrases, expecting the actual reply content on a SEPARATE follow-up
# turn — but people naturally say it all in one breath ("reply tell them
# I'll be late"). REPLY_ALL's triggers are checked first and are more
# specific, so "reply all ..." is never swallowed by the bare "reply "
# prefix as if "all ..." were the reply's own content.
_REPLY_ALL_TRIGGERS = ("reply all to this ", "reply to everyone ", "reply all ")
_REPLY_TRIGGERS = ("reply to this email ", "reply to this ", "reply ")


def match_reply_all_trigger(transcript: str) -> Optional[str]:
    stripped = transcript.strip()
    low = stripped.lower()
    for trigger in _REPLY_ALL_TRIGGERS:
        if low.startswith(trigger):
            content = stripped[len(trigger):].strip()
            if content:
                return content
    return None


def match_reply_trigger(transcript: str) -> Optional[str]:
    stripped = transcript.strip()
    low = stripped.lower()
    for trigger in _REPLY_TRIGGERS:
        if low.startswith(trigger):
            content = stripped[len(trigger):].strip()
            if content:
                return content
    return None


def help_speech(phase: Phase) -> str:
    """A spoken help listing that reflects only what's usable right now (A4)."""
    if phase == "awaiting_confirm":
        return (
            "You can say send to send the message, save as draft to save it "
            "for later, cancel to discard it, start over to begin again, "
            "read it back to hear it again, read the subject, read the "
            "body, or who is it going to. You can also say make it "
            "shorter, make it more formal, make it friendly or firm, or "
            "ask for a change in your own words, and say undo if you "
            "don't like the result. Say copy in and a name to add a CC, "
            "or bcc and a name to blind copy someone, attach a file to "
            "add an attachment, or send this at and a time to schedule "
            "it for later. Say help to hear this list again."
        )
    if phase == "awaiting_address":
        return (
            "Say the name of who this is for, cancel to discard the draft, "
            "or start over to begin again."
        )
    if phase == "awaiting_mode":
        return (
            "Say 'dictate it' if you want me to take down your exact words, "
            "or 'write it for me' if you'd like me to write it for you."
        )
    if phase == "clarifying":
        return (
            "Say the last name of the person you mean, or say an ordinal "
            "like 'one' or 'two', to tell me who you meant."
        )
    if phase == "reading_inbox":
        return (
            "Say next email or previous email to move through your inbox, "
            "who is it from to hear the sender, summarise this one for the "
            "gist, read it in full to hear the whole message, archive this "
            "to remove it, mark as read, reply to answer it, reply all to "
            "answer everyone, or forward this to send it on to someone "
            "else. Say start over to leave your inbox."
        )
    if phase == "review":
        return (
            "Say what you'd like your reply to say, or cancel to discard "
            "it and go back to your inbox."
        )
    if phase == "reading_drafts":
        return (
            "Say next draft or previous draft to move through your saved "
            "drafts, or send to send the one you're on. Say start over to "
            "leave your drafts."
        )
    if phase == "awaiting_schedule_time":
        return (
            "Say what time you'd like this sent, like 5 PM, or tomorrow "
            "at 9 AM, or cancel to discard the draft."
        )
    if phase == "awaiting_pin":
        return "Say your 4-digit PIN to confirm sending, or say cancel to stop."
    return (
        "You can start by saying something like 'tell John I'll be late' "
        "and I'll compose it for you. You can also say cancel, start over, "
        "or help at any time."
    )
