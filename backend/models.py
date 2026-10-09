"""ALL Pydantic contracts — single source of truth. Every module imports from here.

Pydantic v2 syntax only: model_dump() / model_validate(). Never .dict() / .parse_obj().
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field

Phase = Literal[
    "idle",  # nothing in progress
    "awaiting_mode",  # asked dictation-or-brief
    "clarifying",  # asked "which John?"
    "awaiting_address",  # asked for an unknown contact's address
    "review",  # draft exists
    "awaiting_confirm",  # readback done, waiting for "send"
    "reading_inbox",  # navigating messages
    "awaiting_schedule_time",  # asked what time to schedule a send for (F35)
]

Tone = Literal["neutral", "formal", "friendly", "firm", "apologetic"]
Length = Literal["short", "normal", "detailed"]


class Draft(BaseModel):
    recipient: str = ""  # resolved address, or "" if unresolved
    subject: str = ""
    body: str = ""
    recipient_name: str = ""  # human name, for speaking aloud
    cc: list[str] = Field(default_factory=list)
    cc_names: list[str] = Field(default_factory=list)  # human names, for speaking aloud (F29)
    bcc: list[str] = Field(default_factory=list)
    bcc_names: list[str] = Field(default_factory=list)  # human names, for speaking aloud (F29)
    attachments: list[str] = Field(default_factory=list)
    tone: Tone = "neutral"
    length: Length = "normal"
    thread_id: Optional[str] = None  # set when replying
    in_reply_to: Optional[str] = None  # RFC822 Message-Id of the message being replied to
    send_at: Optional[str] = None  # ISO 8601, for scheduled send


class TurnRequest(BaseModel):
    session_id: str = Field(min_length=1)
    transcript: str = ""
    # F54/§11.1 heuristic 1: did the final transcript differ from the last
    # interim result shown before it finalized? None when the turn didn't
    # come from live mic recognition (e.g. a typed command), so it's never
    # confused with a real "no" answer.
    had_interim_change: Optional[bool] = None
    # Phase 11 (§11.2a): the raw text of that last interim result, so
    # backend/uncertainty.py can diff which words changed, not just that
    # something did. Additive alongside had_interim_change above — that
    # field is untouched and still independently populated.
    last_interim_transcript: Optional[str] = None


class SpeechSegment(BaseModel):
    """F53 — one piece of an enhanced readback. `rate="slow"`/`cue=True`
    mark an uncertain (or phonetically spelled) word; everything else is
    a plain, normal-rate chunk. `TurnResponse.speech` already carries the
    flattened text either way, so a client that ignores this list still
    gets a normal sentence.
    """

    text: str
    rate: Literal["normal", "slow"] = "normal"
    cue: bool = False


class TurnResponse(BaseModel):
    speech: str  # THE string the client speaks. Never empty.
    phase: Phase = "idle"
    draft: Optional[Draft] = None  # optional on-screen display only
    awaiting_confirmation: bool = False
    listen_again: bool = True  # hint: reopen the mic after speaking
    ok: bool = True  # false = this turn failed; speech explains it
    focus_target: Optional[str] = None  # element id the frontend should focus() (F30)
    # F53 — None whenever ENHANCED_READBACK=0 (the default); inert for any
    # client that only reads `speech`.
    speech_segments: Optional[list[SpeechSegment]] = None


class MailResult(BaseModel):
    success: bool
    message: str  # a complete, speakable English sentence


class ContactCandidate(BaseModel):
    name: str
    email: str
    score: float = 0.0


class InboxItem(BaseModel):
    id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    unread: bool = True


class ThreadContext(BaseModel):
    """A thread's full readable text, plus what a reply needs to thread
    correctly under it (Phase 6). Defined here, not in gmail/inbox.py,
    so backend/gmail/fake.py can return the same type without an
    inbox.py <-> fake.py circular import.
    """

    text: str
    last_message_id_header: Optional[str] = None  # RFC822 Message-Id, for In-Reply-To/References
    to_recipients: list[str] = Field(default_factory=list)  # F36 reply-all: last message's To
    cc_recipients: list[str] = Field(default_factory=list)  # F36 reply-all: last message's Cc


class Prefs(BaseModel):
    """F45 — speech-rate persistence. Global, not per-session: this is a
    single-user app, and F45 explicitly says "across sessions."
    """

    speech_rate: float = 1.0


class RecoverableDraftResponse(BaseModel):
    """GET /api/draft/recoverable (F56, §13.2)."""

    recoverable: bool
    draft: Optional[Draft] = None
    speech: str = ""  # the spoken offer, "" when recoverable is False


class DraftComposeRequest(BaseModel):
    """POST /api/draft/compose (§21) — direct access for testing without
    the frontend/session machinery. `mode` is optional; when omitted,
    routes/draft.py falls back to mode_detect.detect_mode().
    """

    transcript: str
    mode: Optional[Literal["dictation", "brief"]] = None


class DraftEditRequest(BaseModel):
    """POST /api/draft/edit (§21) — same direct-access pattern."""

    draft: Draft
    instruction: str
