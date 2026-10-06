"""POST /api/turn — THE orchestrator (§24).

Order of checks, every turn:
  1. empty transcript          -> ask again
  2. matches command grammar   -> handle deterministically (never touches AI)
  3. otherwise, branch on the session's current phase

Composition/editing (Phase 3) and contact resolution (Phase 4) are both
real now: backend/ai/compose.py, mode_detect.py, edit.py, and
backend/data/contacts.py::resolve_recipient(). `_resolve_recipient_stub`
survives only as the permissive fallback used once inside
`awaiting_address` (F16's "just accept anything and move on" escape
hatch), never for the initial resolution attempt anymore.
"""

import re
import time
from typing import Optional

from fastapi import APIRouter

from backend.ai import mode_detect
from backend.ai.compose import compose_email, compose_reply
from backend.ai.edit import revise
from backend.ai.summarize import summarize
from backend.attachments import get_last_attachment
from backend.commands import (
    EDIT_INSTRUCTIONS,
    FORCED_LENGTH,
    FORCED_TONE,
    help_speech,
    match_bcc_trigger,
    match_cc_trigger,
    match_schedule_trigger,
    parse_command,
)
from backend.data.contacts import increment_use_count, match_clarifying_answer, resolve_cc_hint, resolve_recipient
from backend.data.prefs import get_tone_for_recipient, record_phrase, set_tone_for_recipient
from backend.errors import SpokenError, to_spoken
from backend.events import categorize_error, classify_repair_turn, log_event, set_current_session
from backend.gmail.inbox import archive, get_my_email, get_thread_context, list_unread, mark_read
from backend.gmail.schedule import parse_schedule_time, schedule_send
from backend.gmail.send import save_draft, send_email
from backend.models import Draft, TurnRequest, TurnResponse
from backend.session import ConversationState, get_session, reset_session
from backend.speechify import (
    build_disambiguation_question,
    build_full_message_readback,
    build_inbox_listing,
    build_readback,
    describe_inbox_item,
    read_body,
    read_recipient,
    read_subject,
    speak_schedule_time,
    speakable_email,
    summarize_draft,
)
from backend.text_correction import strip_correction

router = APIRouter()

_CATCH_NOTHING_HEARD = "I didn't catch that. Could you say it again?"
_SEND_TOO_EARLY = "I haven't read the message back to you yet. Say 'read it back' first."
_CANCELLED = "Cancelled. Nothing was sent."
_RESTARTED = "Okay, starting over. Say something like 'tell John I'll be late' whenever you're ready."
_ASK_WHO = "Who should I send this to?"
_NOT_YET_AVAILABLE = "That's not available yet. Say help to hear what you can do."
_NO_DRAFT_TO_READ = "There's no message to read yet."
_NO_DRAFT_TO_CHANGE = "There's no message to change yet. Say something like 'tell John I'll be late' to start one."
_NOTHING_TO_UNDO = "There's nothing to undo."
_NOTHING_TO_REDO = "There's nothing to redo."
_DID_NOT_CATCH_MODE_ANSWER = "Sorry, I didn't catch that. " + mode_detect.ASK_MODE_QUESTION
_OVERRIDE_DICTATION_ACK = "Okay, go ahead — I'll take it down word for word."
_OVERRIDE_BRIEF_ACK = "Okay, tell me what you'd like to say and I'll write it for you."
_DID_NOT_CATCH_CLARIFYING_ANSWER = "Sorry, I didn't catch that. {question}"
_NO_DRAFT_TO_SAVE = "There's no message to save yet. Say something like 'tell John I'll be late' to start one."
_RECONNECT_MESSAGE = (
    "Reconnecting your email happens outside of voice, since it needs a real sign-in "
    "screen. Whoever set this app up can run the email connect step again."
)
_NO_INBOX_LOADED = "You haven't opened your inbox yet. Say 'read my unread mail' to start."
_INBOX_BLOCKED_MID_DRAFT = (
    "You're in the middle of a message. Finish it, save it, or say cancel before "
    "reading your inbox."
)
_AT_LAST_EMAIL = "That's the last message."
_AT_FIRST_EMAIL = "That's the first message."
_ASK_REPLY_CONTENT = "What would you like to say?"

# READ_INBOX is refused in any phase where a draft is genuinely in progress
# — the same guard SEND already applies, so "read my unread mail" can never
# silently abandon whatever was being composed.
_MID_DRAFT_PHASES = {"awaiting_confirm", "clarifying", "awaiting_address", "awaiting_mode", "review"}

# CC/attach/attach-last/schedule (Phase 7) are all only meaningful once a
# draft has been composed AND read back — same guard style as SEND/SAVE_DRAFT.
_NEEDS_READY_DRAFT = (
    "That's only available once I've read your message back to you. "
    "Say something like 'tell John I'll be late' to start one."
)
_ATTACH_INSTRUCTION = (
    "Tap the Attach a file button to choose a file — I can't open the file "
    "picker by voice alone."
)
_ATTACH_BUTTON_ID = "attach-btn"
_NO_PRIOR_ATTACHMENT = "You haven't attached anything yet this session. Say attach a file to choose one."
_ADD_CC_INSTRUCTION = "Say add cc and then a name, like add cc Sarah, or copy in Sarah."
_ADD_BCC_INSTRUCTION = "Say add bcc and then a name, like add bcc Sarah."
_ASK_FORWARD_RECIPIENT = "Forwarding this message. Who would you like to send it to?"


def _resolve_recipient_stub(hint: str) -> tuple[str, str]:
    """F16's permissive escape hatch, used only inside `awaiting_address`.

    Accepts any spoken name and manufactures a placeholder address —
    "accept a spelled-out or dictated address" per F16, without building
    real address-string parsing (e.g. "priya at gmail dot com"), which is
    a deliberate, explicit scope limit for this phase, not an oversight.
    """
    hint = hint.strip()
    if not hint:
        return "", ""
    slug = re.sub(r"[^a-z0-9]+", ".", hint.lower()).strip(".") or "contact"
    return hint.title(), f"{slug}@example.com"


def _unknown_contact_message(hint: str) -> str:
    return f"I don't have a contact called {hint.strip().title()}. Who should I send this to?"


def _forward_subject(original_subject: str) -> str:
    stripped = original_subject.strip()
    if not stripped:
        return "Fwd:"
    if stripped.lower().startswith("fwd:"):
        return stripped
    return f"Fwd: {stripped}"


def _forward_body(sender_name: str, subject: str, thread_text: str) -> str:
    """F36: plain prose, not a decorative ASCII header — confirmed
    `normalize_for_speech()`'s markdown-stripping regex doesn't touch
    hyphens, so a Gmail-style "----- Forwarded message -----" divider
    would be read aloud as a run of spoken dashes. One body field serves
    both the literal sent content and the spoken readback, so the same
    plain-prose wording is used for both.
    """
    who = sender_name or "someone"
    subj = subject.strip() or "no subject"
    return f"Forwarded message from {who}, subject {subj}: {thread_text.strip()}"


def _reply_subject(original_subject: str) -> str:
    stripped = original_subject.strip()
    if not stripped:
        return "Re:"
    if stripped.lower().startswith("re:"):
        return stripped
    return f"Re: {stripped}"


def _apply_tone_default(draft: Draft, email: str) -> None:
    """F42, fresh-compose fidelity: field-only (see the plan's "Applying
    the default back has two different fidelities" note). Shared by every
    place a recipient gets resolved for a fresh compose — the normal
    fuzzy/alias/group path, the `clarifying` answer, AND the
    `awaiting_address` escape-hatch fallback all need this, not just the
    first one (a real gap live-testing caught: the fallback path resolves
    plenty of real-world names a small seed contacts DB doesn't know yet).
    Skipped for a group recipient (comma-joined emails).
    """
    if email and "," not in email:
        stored_tone = get_tone_for_recipient(email)
        if stored_tone:
            draft.tone = stored_tone


def _extract_opener(body: str) -> str:
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    return lines[0] if lines else ""


def _extract_signoff(body: str) -> str:
    lines = [line.strip() for line in body.split("\n") if line.strip()]
    return lines[-1] if lines else ""


def _record_personalisation_on_send(draft: Draft) -> None:
    """F42/F44: called on SEND success, before reset_session() wipes the
    draft. Skipped for a group recipient (comma-joined addresses) — no
    single tone_history row to key by. F44 is bookkeeping only (your
    choice, Phase 8 plan): record_phrase() never feeds back into a
    generated email anywhere in this app.
    """
    if "," not in draft.recipient:
        set_tone_for_recipient(draft.recipient, draft.tone)
    record_phrase(_extract_opener(draft.body))
    record_phrase(_extract_signoff(draft.body))


def _log_draft_created(state: ConversationState, mode: str) -> None:
    """F54: the one point where `draft_created` is logged, called the
    instant a draft's body first becomes non-empty — fresh compose, a
    reply/reply-all's content turn, and forward all funnel through here.
    """
    log_event(
        state.session_id,
        "draft_created",
        phase=state.phase,
        detail={
            "mode": mode,
            "body_words": len(state.draft.body.split()),
            "subject_words": len(state.draft.subject.split()),
        },
        content={"body": state.draft.body, "subject": state.draft.subject},
    )


def _try_mark_read(message_id: str) -> None:
    """Best-effort mark-read used by SUMMARISE/READ_FULL: a labeling
    failure must never mask the answer the user actually asked for. The
    explicit MARK_READ command does NOT use this — there, the failure IS
    the answer, so it's spoken directly instead.
    """
    try:
        mark_read(message_id)
    except Exception:  # noqa: BLE001 - deliberately swallowed, see docstring
        pass


def _handle_cc_trigger(state: ConversationState, hint: str) -> TurnResponse:
    """F29: "copy in Sarah" / "add cc Sarah". Deliberately scoped to
    deterministic-only resolution — an ambiguous hint is a flat, spoken
    failure, never a second clarifying sub-conversation (see
    contacts.py::resolve_cc_hint's docstring).
    """
    if state.phase != "awaiting_confirm":
        return _respond(state, _NEEDS_READY_DRAFT)

    result = resolve_cc_hint(hint)
    if result.status != "resolved":
        return _respond(
            state,
            f"I couldn't tell who you meant by {hint.strip().title()} for the CC. Say a full name.",
        )

    # A group match (e.g. "the team") returns comma-joined names/emails for
    # several people at once — split and extend in lockstep so
    # speechify.py's _cc_names can pair them up positionally.
    names = [n.strip() for n in result.name.split(",")]
    emails = [e.strip() for e in result.email.split(",")]
    state.draft.cc.extend(emails)
    state.draft.cc_names.extend(names)
    return _respond(state, _speak_readback(state))


def _handle_bcc_trigger(state: ConversationState, hint: str) -> TurnResponse:
    """F29: "bcc Sarah" / "add bcc Sarah" — exact mirror of
    _handle_cc_trigger(), writing to draft.bcc/bcc_names instead.
    """
    if state.phase != "awaiting_confirm":
        return _respond(state, _NEEDS_READY_DRAFT)

    result = resolve_cc_hint(hint)
    if result.status != "resolved":
        return _respond(
            state,
            f"I couldn't tell who you meant by {hint.strip().title()} for the BCC. Say a full name.",
        )

    names = [n.strip() for n in result.name.split(",")]
    emails = [e.strip() for e in result.email.split(",")]
    state.draft.bcc.extend(emails)
    state.draft.bcc_names.extend(names)
    return _respond(state, _speak_readback(state))


def _resolve_schedule_phrase(state: ConversationState, session_id: str, phrase: str) -> TurnResponse:
    """Shared by the initial "schedule this for {phrase}" trigger and the
    follow-up answer once in `awaiting_schedule_time` — both just need a
    time phrase parsed and acted on the same way.
    """
    # If the answer redundantly restates the trigger phrase ("schedule
    # this for 5am" instead of just "5am" — plausible once already in
    # awaiting_schedule_time), strip it so the bare time still parses.
    restated = match_schedule_trigger(phrase)
    if restated is not None:
        phrase = restated

    result = parse_schedule_time(phrase)

    if result.status in ("ambiguous", "invalid"):
        state.phase = "awaiting_schedule_time"
        return _respond(state, result.message)

    state.draft.send_at = result.when.isoformat()
    mail_result = schedule_send(state.draft)
    if not mail_result.success:
        return _respond(state, mail_result.message, ok=False)

    who = state.draft.recipient_name or state.draft.recipient
    time_speech = speak_schedule_time(
        result.when, rolled_to_tomorrow=result.rolled_to_tomorrow, is_tomorrow=result.is_tomorrow
    )
    speech = f"Okay, I'll send this to {who} at {time_speech}."

    reset_session(session_id)
    state = get_session(session_id)
    return _respond(state, speech)


def _handle_schedule_trigger(state: ConversationState, session_id: str, phrase: str) -> TurnResponse:
    if state.phase != "awaiting_confirm":
        return _respond(state, _NEEDS_READY_DRAFT)
    return _resolve_schedule_phrase(state, session_id, phrase)


def _respond(
    state: ConversationState, speech: str, *, ok: bool = True, focus_target: Optional[str] = None
) -> TurnResponse:
    state.last_speech = speech
    if not ok:
        log_event(state.session_id, "error_spoken", phase=state.phase, detail={"category": categorize_error(speech)})
    return TurnResponse(
        speech=speech,
        phase=state.phase,
        draft=state.draft,
        awaiting_confirmation=(state.phase == "awaiting_confirm"),
        ok=ok,
        focus_target=focus_target,
    )


def _speak_readback(state: ConversationState) -> str:
    """F54: the one point where `readback_start` is logged — every other
    call site speaks a draft back via this wrapper instead of calling
    build_readback() directly. `enhanced` is schema-reserved for Phase
    11's ENHANCED_READBACK flag and is always False here.
    """
    log_event(
        state.session_id,
        "readback_start",
        phase=state.phase,
        detail={"body_words": len(state.draft.body.split()), "enhanced": False},
    )
    return build_readback(state.draft)


def _compose_and_readback(state: ConversationState, transcript: str, mode: str) -> TurnResponse:
    try:
        draft, recipient_hint = compose_email(transcript, mode)
    except SpokenError as exc:
        return _respond(state, to_spoken(exc), ok=False)

    state.draft = draft
    state.mode = mode
    _log_draft_created(state, mode)

    result = resolve_recipient(recipient_hint, transcript)

    if result.status == "empty":
        state.phase = "awaiting_address"
        return _respond(state, _ASK_WHO)

    if result.status == "unknown":
        state.phase = "awaiting_address"
        return _respond(state, _unknown_contact_message(recipient_hint))

    if result.status == "clarifying":
        state.candidates = result.candidates
        state.clarifying_hint = recipient_hint
        state.phase = "clarifying"
        return _respond(state, result.question)

    # resolved (alias, group, or a clean fuzzy winner)
    state.draft.recipient_name = result.name
    state.draft.recipient = result.email
    _apply_tone_default(state.draft, result.email)
    state.phase = "awaiting_confirm"
    return _respond(state, _speak_readback(state))


def _start_composing(state: ConversationState, transcript: str) -> TurnResponse:
    """Entry point for a fresh utterance at idle phase — mode detection
    (F3/F4/F5) runs before any composition happens.
    """
    if state.mode:
        # A standalone override ("dictate this") was declared last turn
        # (see below); this whole turn's transcript is the content. Idle
        # phase is only ever reached with state.mode already set via that
        # path — any prior draft's mode was cleared by reset_session().
        return _compose_and_readback(state, transcript, state.mode)

    override = mode_detect.check_override(transcript)
    if override is not None:
        mode, remainder = override
        if remainder:
            return _compose_and_readback(state, remainder, mode)
        state.mode = mode
        ack = _OVERRIDE_DICTATION_ACK if mode == "dictation" else _OVERRIDE_BRIEF_ACK
        return _respond(state, ack)

    try:
        result = mode_detect.detect_mode(transcript)
    except SpokenError as exc:
        return _respond(state, to_spoken(exc), ok=False)

    if result.ask:
        state.phase = "awaiting_mode"
        state.pending_transcript = transcript
        return _respond(state, mode_detect.ASK_MODE_QUESTION)

    return _compose_and_readback(state, transcript, result.mode)


def _apply_edit(
    state: ConversationState,
    instruction: str,
    *,
    forced_tone: Optional[str] = None,
    forced_length: Optional[str] = None,
) -> TurnResponse:
    """Shared by the grammar-matched tone/length commands and the F27
    free-form edit fallback. Undo history is only pushed on success, so a
    failed revision never leaves a no-op undo entry behind.
    """
    if state.phase != "awaiting_confirm":
        return _respond(state, _NO_DRAFT_TO_CHANGE)

    previous = state.draft.model_copy(deep=True)
    try:
        new_draft = revise(state.draft, instruction)
    except SpokenError as exc:
        return _respond(state, to_spoken(exc), ok=False)

    if forced_tone is not None:
        new_draft.tone = forced_tone
    if forced_length is not None:
        new_draft.length = forced_length

    state.history.append(previous)
    state.redo_stack.clear()
    state.draft = new_draft

    kind = "tone" if forced_tone is not None else "length" if forced_length is not None else "free_form"
    log_event(state.session_id, "edit_requested", phase=state.phase, detail={"kind": kind})
    log_event(
        state.session_id,
        "repair_turn",
        phase=state.phase,
        detail={"reason": classify_repair_turn(late_edit=True)},
    )
    return _respond(state, _speak_readback(state))


def _handle_command(state: ConversationState, session_id: str, intent: str) -> TurnResponse:
    if intent == "SEND":
        if state.phase != "awaiting_confirm":
            return _respond(state, _SEND_TOO_EARLY)
        log_event(
            session_id,
            "send_confirmed",
            phase=state.phase,
            detail={},
            content={"recipient": state.draft.recipient},
        )
        start = time.monotonic()
        result = send_email(state.draft)
        log_event(
            session_id,
            "send_result",
            phase=state.phase,
            ms=int((time.monotonic() - start) * 1000),
            detail={
                "success": result.success,
                "error_category": None if result.success else categorize_error(result.message),
            },
        )
        if result.success:
            _record_personalisation_on_send(state.draft)
            reset_session(session_id)
            state = get_session(session_id)
        return _respond(state, result.message, ok=result.success)

    if intent == "SAVE_DRAFT":
        if state.phase != "awaiting_confirm":
            return _respond(state, _NO_DRAFT_TO_SAVE)
        result = save_draft(state.draft)
        if result.success:
            # Handed off to Gmail as a real draft — this phase doesn't
            # track its remote ID, so continuing to edit the local copy
            # would be misleading. Same reset-on-success pattern as SEND.
            reset_session(session_id)
            state = get_session(session_id)
        return _respond(state, result.message, ok=result.success)

    if intent == "RECONNECT":
        return _respond(state, _RECONNECT_MESSAGE)

    if intent == "CANCEL":
        reset_session(session_id)
        state = get_session(session_id)
        return _respond(state, _CANCELLED)

    if intent == "RESTART":
        prior_phase = state.phase
        reset_session(session_id)
        state = get_session(session_id)
        log_event(
            session_id,
            "repair_turn",
            phase=prior_phase,
            detail={"reason": classify_repair_turn(start_over=True)},
        )
        return _respond(state, _RESTARTED)

    if intent == "HELP":
        return _respond(state, help_speech(state.phase))

    if intent in ("READ_SUBJECT", "READ_BODY", "READ_RECIPIENT"):
        if state.phase != "awaiting_confirm":
            return _respond(state, _NO_DRAFT_TO_READ)
        if intent == "READ_SUBJECT":
            return _respond(state, read_subject(state.draft))
        if intent == "READ_BODY":
            return _respond(state, read_body(state.draft))
        return _respond(state, read_recipient(state.draft))

    if intent == "UNDO":
        if not state.history:
            return _respond(state, _NOTHING_TO_UNDO)
        state.redo_stack.append(state.draft.model_copy(deep=True))
        state.draft = state.history.pop()
        log_event(session_id, "edit_requested", phase=state.phase, detail={"kind": "undo"})
        log_event(
            session_id, "repair_turn", phase=state.phase, detail={"reason": classify_repair_turn(undo=True)}
        )
        return _respond(state, f"Undone. {summarize_draft(state.draft)}")

    if intent == "REDO":
        if not state.redo_stack:
            return _respond(state, _NOTHING_TO_REDO)
        state.history.append(state.draft.model_copy(deep=True))
        state.draft = state.redo_stack.pop()
        log_event(session_id, "edit_requested", phase=state.phase, detail={"kind": "redo"})
        log_event(
            session_id, "repair_turn", phase=state.phase, detail={"reason": classify_repair_turn(redo=True)}
        )
        return _respond(state, f"Redone. {summarize_draft(state.draft)}")

    if intent in EDIT_INSTRUCTIONS:
        return _apply_edit(
            state,
            EDIT_INSTRUCTIONS[intent],
            forced_tone=FORCED_TONE.get(intent),
            forced_length=FORCED_LENGTH.get(intent),
        )

    if intent == "READ_INBOX":
        if state.phase in _MID_DRAFT_PHASES:
            return _respond(state, _INBOX_BLOCKED_MID_DRAFT)
        try:
            items = list_unread(limit=10)
        except Exception as exc:  # noqa: BLE001 - never fail silently (A5)
            return _respond(state, to_spoken(exc), ok=False)
        state.inbox = items
        state.inbox_index = 0
        state.phase = "reading_inbox" if items else "idle"
        return _respond(state, build_inbox_listing(items))

    if intent in ("NEXT_EMAIL", "PREV_EMAIL"):
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        if intent == "NEXT_EMAIL":
            if state.inbox_index >= len(state.inbox) - 1:
                return _respond(state, _AT_LAST_EMAIL)
            state.inbox_index += 1
        else:
            if state.inbox_index <= 0:
                return _respond(state, _AT_FIRST_EMAIL)
            state.inbox_index -= 1
        return _respond(state, describe_inbox_item(state.inbox[state.inbox_index]))

    if intent == "READ_SENDER":
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        item = state.inbox[state.inbox_index]
        sender_speech = item.sender_name or speakable_email(item.sender_email) or "someone"
        return _respond(state, f"This one is from {sender_speech}.")

    if intent in ("SUMMARISE", "READ_FULL"):
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        item = state.inbox[state.inbox_index]
        try:
            thread_text = get_thread_context(item.thread_id).text
            speech = summarize(thread_text) if intent == "SUMMARISE" else build_full_message_readback(thread_text)
        except Exception as exc:  # noqa: BLE001
            return _respond(state, to_spoken(exc), ok=False)
        _try_mark_read(item.id)
        item.unread = False
        return _respond(state, speech)

    if intent == "ARCHIVE":
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        item = state.inbox[state.inbox_index]
        result = archive(item.id)
        if not result.success:
            return _respond(state, result.message, ok=False)
        del state.inbox[state.inbox_index]
        if not state.inbox:
            state.inbox_index = 0
            state.phase = "idle"
            return _respond(state, "Archived. Your inbox is empty now.")
        if state.inbox_index >= len(state.inbox):
            state.inbox_index = len(state.inbox) - 1
        return _respond(state, f"Archived. {describe_inbox_item(state.inbox[state.inbox_index])}")

    if intent == "MARK_READ":
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        item = state.inbox[state.inbox_index]
        try:
            mark_read(item.id)
        except Exception as exc:  # noqa: BLE001 - explicit command: the failure IS the answer
            return _respond(state, to_spoken(exc), ok=False)
        item.unread = False
        return _respond(state, "Marked as read.")

    if intent == "REPLY":
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        item = state.inbox[state.inbox_index]
        try:
            context = get_thread_context(item.thread_id)
        except Exception as exc:  # noqa: BLE001
            return _respond(state, to_spoken(exc), ok=False)
        state.draft = Draft(
            recipient=item.sender_email,
            recipient_name=item.sender_name,
            subject=_reply_subject(item.subject),
            thread_id=item.thread_id,
            in_reply_to=context.last_message_id_header,
        )
        # F42: the recipient IS known already for a reply (unlike a fresh
        # compose), so this pre-set carries all the way into compose_reply()
        # below once the user says what to write — see the "review" phase
        # branch in _handle_turn.
        _apply_tone_default(state.draft, item.sender_email)
        state.phase = "review"
        who = item.sender_name or speakable_email(item.sender_email) or "them"
        return _respond(state, f"Replying to {who}. {_ASK_REPLY_CONTENT}")

    if intent == "REPLY_ALL":
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        item = state.inbox[state.inbox_index]
        try:
            context = get_thread_context(item.thread_id)
            my_email = get_my_email()
        except Exception as exc:  # noqa: BLE001
            return _respond(state, to_spoken(exc), ok=False)

        # Everyone the original message went to, minus the sender (already
        # becoming the primary recipient) and "my own" address — no
        # contact-DB names exist for addresses pulled straight off a
        # header, so cc_names is left shorter than cc; _cc_speech() already
        # tolerates that, falling back to speakable_email() per address.
        exclude = {item.sender_email.lower(), my_email.lower()}
        seen: set[str] = set()
        others = []
        for addr in context.to_recipients + context.cc_recipients:
            low = addr.lower()
            if low in exclude or low in seen:
                continue
            seen.add(low)
            others.append(addr)

        state.draft = Draft(
            recipient=item.sender_email,
            recipient_name=item.sender_name,
            subject=_reply_subject(item.subject),
            thread_id=item.thread_id,
            in_reply_to=context.last_message_id_header,
            cc=others,
        )
        _apply_tone_default(state.draft, item.sender_email)
        state.phase = "review"
        who = item.sender_name or speakable_email(item.sender_email) or "them"
        return _respond(state, f"Replying to {who} and everyone else on the thread. {_ASK_REPLY_CONTENT}")

    if intent == "FORWARD":
        if state.phase != "reading_inbox" or not state.inbox:
            return _respond(state, _NO_INBOX_LOADED)
        item = state.inbox[state.inbox_index]
        try:
            context = get_thread_context(item.thread_id)
        except Exception as exc:  # noqa: BLE001
            return _respond(state, to_spoken(exc), ok=False)
        state.draft = Draft(
            subject=_forward_subject(item.subject),
            body=_forward_body(item.sender_name, item.subject, context.text),
        )
        state.phase = "awaiting_address"
        _log_draft_created(state, "forward")
        return _respond(state, _ASK_FORWARD_RECIPIENT)

    if intent == "ADD_CC":
        if state.phase != "awaiting_confirm":
            return _respond(state, _NEEDS_READY_DRAFT)
        return _respond(state, _ADD_CC_INSTRUCTION)

    if intent == "ADD_BCC":
        if state.phase != "awaiting_confirm":
            return _respond(state, _NEEDS_READY_DRAFT)
        return _respond(state, _ADD_BCC_INSTRUCTION)

    if intent == "KEEP_GOING":
        # F10: the exact phrase the app tells users to say after an
        # auto-stop. A no-op — phase/draft untouched, relying on
        # TurnResponse.listen_again's default True so the mic reopens.
        # Without this, the literal words "keep going" would fall through
        # and risk being treated as compose/edit content.
        return _respond(state, "Go ahead, I'm listening.")

    if intent == "NEW_PARAGRAPH":
        # Almost always dead in practice — the real F28 effect is the text
        # substitution in ai/compose.py, applied while composing. If this
        # somehow DOES arrive as its own whole turn while a draft is ready,
        # give it real behaviour instead of leaving it silently inert.
        if state.phase != "awaiting_confirm":
            return _respond(state, _NEEDS_READY_DRAFT)
        previous = state.draft.model_copy(deep=True)
        state.draft.body = state.draft.body.rstrip() + "\n\n"
        state.history.append(previous)
        state.redo_stack.clear()
        return _respond(state, _speak_readback(state))

    if intent == "ATTACH":
        if state.phase != "awaiting_confirm":
            return _respond(state, _NEEDS_READY_DRAFT)
        return _respond(state, _ATTACH_INSTRUCTION, focus_target=_ATTACH_BUTTON_ID)

    if intent == "ATTACH_LAST":
        if state.phase != "awaiting_confirm":
            return _respond(state, _NEEDS_READY_DRAFT)
        path = get_last_attachment(session_id)
        if not path:
            return _respond(state, _NO_PRIOR_ATTACHMENT, focus_target=_ATTACH_BUTTON_ID)
        state.draft.attachments.append(path)
        return _respond(state, _speak_readback(state))

    # REPEAT
    if state.phase == "awaiting_confirm" and state.draft.body:
        speech = _speak_readback(state)
    elif state.last_speech:
        speech = state.last_speech
    else:
        speech = "There's nothing to repeat yet."
    return _respond(state, speech)


def _handle_turn(req: TurnRequest) -> TurnResponse:
    state = get_session(req.session_id)
    set_current_session(req.session_id)
    transcript = req.transcript.strip()

    log_event(
        req.session_id,
        "turn_start",
        phase=state.phase,
        detail={"transcript_words": len(transcript.split())},
        content={"transcript": transcript},
    )
    log_event(
        req.session_id,
        "asr_result",
        phase=state.phase,
        detail={
            "words": len(transcript.split()),
            # Confidence stays unpopulated until Phase 11 verifies whether
            # the browser's confidence signal is usable at all (§11.1) —
            # the columns exist now so that phase only has to fill them in.
            "min_confidence": None,
            "mean_confidence": None,
            "had_interim_change": req.had_interim_change,
        },
    )

    # F9: "no wait, change that to…" — a single hook point, before anything
    # else touches the transcript, covers every phase uniformly. Re-check
    # for empty AFTER stripping: a correction-marker-only utterance
    # ("scratch that" alone) legitimately has nothing left to act on.
    original_transcript = transcript
    transcript = strip_correction(transcript)

    if transcript != original_transcript:
        log_event(
            req.session_id,
            "repair_turn",
            phase=state.phase,
            detail={"reason": classify_repair_turn(self_corrected=True)},
        )

    if not transcript:
        return _respond(state, _CATCH_NOTHING_HEARD)

    intent = parse_command(transcript)
    if intent is not None:
        log_event(req.session_id, "command_matched", phase=state.phase, detail={"intent": intent})
        return _handle_command(state, req.session_id, intent)

    # Checked BEFORE the generic trigger-matching below: once we're
    # already dedicated to collecting a schedule time, every non-command
    # transcript is a time answer, even one that happens to start with a
    # CC/schedule trigger phrase (_resolve_schedule_phrase itself strips a
    # redundantly-restated "schedule this for" prefix).
    if state.phase == "awaiting_schedule_time":
        return _resolve_schedule_phrase(state, req.session_id, transcript)

    # F29/F35: free-form content (a name, a time) can never be a literal
    # _PHRASES key — these are prefix-matched separately, the same way
    # mode_detect.check_override() handles F4's "dictate this ...".
    cc_hint = match_cc_trigger(transcript)
    if cc_hint is not None:
        return _handle_cc_trigger(state, cc_hint)

    bcc_hint = match_bcc_trigger(transcript)
    if bcc_hint is not None:
        return _handle_bcc_trigger(state, bcc_hint)

    schedule_phrase = match_schedule_trigger(transcript)
    if schedule_phrase is not None:
        return _handle_schedule_trigger(state, req.session_id, schedule_phrase)

    if state.phase == "idle":
        return _start_composing(state, transcript)

    if state.phase == "awaiting_mode":
        mode = mode_detect.match_mode_answer(transcript)
        if mode is None:
            return _respond(state, _DID_NOT_CATCH_MODE_ANSWER)
        pending = state.pending_transcript
        state.phase = "idle"
        state.pending_transcript = ""
        return _compose_and_readback(state, pending, mode)

    if state.phase == "clarifying":
        matched = match_clarifying_answer(transcript, state.candidates)
        if matched is None:
            # Rebuilt fresh from (hint, candidates) every time, never
            # from the previous spoken sentence — reusing the prior
            # question text would compound the "sorry" prefix on a
            # second consecutive mismatch.
            log_event(
                req.session_id,
                "repair_turn",
                phase=state.phase,
                detail={"reason": classify_repair_turn(reclarify=True)},
            )
            question = build_disambiguation_question(state.clarifying_hint, state.candidates)
            return _respond(state, _DID_NOT_CATCH_CLARIFYING_ANSWER.format(question=question))

        increment_use_count(matched.email)
        state.draft.recipient_name = matched.name
        state.draft.recipient = matched.email
        _apply_tone_default(state.draft, matched.email)
        state.candidates = []
        state.clarifying_hint = ""
        state.phase = "awaiting_confirm"
        return _respond(state, _speak_readback(state))

    if state.phase == "awaiting_address":
        recipient_name, recipient = _resolve_recipient_stub(transcript)
        state.draft.recipient_name = recipient_name
        state.draft.recipient = recipient
        _apply_tone_default(state.draft, recipient)
        state.phase = "awaiting_confirm"
        return _respond(state, _speak_readback(state))

    if state.phase == "awaiting_confirm":
        # Not a known command (checked above) and not a grammar-matched
        # tone/length command either — treat the whole transcript as a
        # free-form edit instruction (F27), e.g. "remove the last sentence".
        return _apply_edit(state, transcript)

    if state.phase == "review":
        # A reply-in-progress: the transcript IS the reply content. Fed
        # straight into compose_reply(), never through edit.py::revise()
        # — revise() expects an existing body plus a change instruction,
        # and a reply's body starts empty, so that would produce nonsense.
        try:
            thread_text = get_thread_context(state.draft.thread_id or "").text
            # Only a REAL learned default counts as a hint — "neutral" is
            # also the Draft model's own untouched default, so passing it
            # through would be indistinguishable from "no hint" anyway.
            tone_hint = state.draft.tone if state.draft.tone != "neutral" else None
            reply_draft = compose_reply(transcript, thread_text, tone_hint=tone_hint)
        except Exception as exc:  # noqa: BLE001
            return _respond(state, to_spoken(exc), ok=False)
        state.draft.body = reply_draft.body
        state.draft.tone = reply_draft.tone
        state.draft.length = reply_draft.length
        state.phase = "awaiting_confirm"
        _log_draft_created(state, "reply")
        return _respond(state, _speak_readback(state))

    # reading_inbox: everything reachable here is a grammar-matched command
    # (handled above via _handle_command), so free text that falls through
    # is genuinely unrecognized. Safety net so nothing ever fails silently.
    return _respond(state, _NOT_YET_AVAILABLE)


@router.post("/turn", response_model=TurnResponse)
def turn(req: TurnRequest) -> TurnResponse:
    try:
        return _handle_turn(req)
    except SpokenError as exc:
        # Bypasses _respond() entirely (no ConversationState reached this
        # far), so this is the one place error_spoken can't be centralized
        # through it — logged here instead, same categorize_error() helper.
        log_event(req.session_id, "error_spoken", detail={"category": categorize_error(exc.message)})
        return TurnResponse(speech=to_spoken(exc), ok=False)
    except Exception as exc:  # noqa: BLE001 - last-resort safety net, rule A5
        log_event(req.session_id, "error_spoken", detail={"category": type(exc).__name__})
        return TurnResponse(speech=to_spoken(exc), ok=False)
