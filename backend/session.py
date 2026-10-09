"""Conversation state — one ConversationState per session_id, held in memory.

In-memory is deliberate: single user, no database server needed. The
frontend generates a UUID once per page load and holds it in a JS variable.
"""

from typing import Optional

from pydantic import BaseModel

from backend.models import ContactCandidate, Draft, InboxItem, Phase, SpeechSegment


class ConversationState(BaseModel):
    session_id: str
    phase: Phase = "idle"
    draft: Draft = Draft()
    history: list[Draft] = []  # undo stack
    redo_stack: list[Draft] = []
    candidates: list[ContactCandidate] = []
    clarifying_hint: str = ""  # original hint, remembered while clarifying (F13)
    mode: Optional[str] = None  # "dictation" | "brief"
    pending_transcript: str = ""  # remembered while awaiting_mode (F5)
    last_speech: str = ""  # for "repeat that"
    inbox: list[InboxItem] = []
    inbox_index: int = 0
    # F52 (Phase 11): "the current field being discussed" for a bare
    # "spell that" — defaults to "recipient" right after any readback
    # (recipient is always read first), updated by READ_SUBJECT/
    # READ_BODY/READ_RECIPIENT.
    last_field_named: Optional[str] = None
    # F53: set once by _speak_readback(), consumed immediately by
    # _respond() on the same turn — a transient, one-shot handoff, the
    # same pattern last_speech already uses.
    pending_speech_segments: Optional[list[SpeechSegment]] = None
    # F59 (Phase 12): set only when "clarifying" is entered BEFORE anything
    # is composed (a recipient hint was found and resolved first) — "" means
    # the old shape, where a draft already exists by the time this resolves.
    pending_recipient_transcript: str = ""
    # F57 (Phase 13): set when an attachment's full text was summarized
    # instead of read, so a follow-up "read it in full" knows what to
    # speak. "" means no such offer is pending.
    pending_attachment_text: str = ""
    # F51 (Phase 14, optional) — wrong-PIN attempts against the current
    # pending send; reset once back to awaiting_confirm.
    pin_attempts: int = 0


_sessions: dict[str, ConversationState] = {}


def get_session(session_id: str) -> ConversationState:
    """Return the existing session, or create a fresh idle one."""
    if session_id not in _sessions:
        _sessions[session_id] = ConversationState(session_id=session_id)
    return _sessions[session_id]


def reset_session(session_id: str) -> ConversationState:
    """Clear a session back to a fresh idle state (F32, F37)."""
    _sessions[session_id] = ConversationState(session_id=session_id)
    return _sessions[session_id]
