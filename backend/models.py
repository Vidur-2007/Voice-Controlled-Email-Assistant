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
    attachments: list[str] = Field(default_factory=list)
    tone: Tone = "neutral"
    length: Length = "normal"
    thread_id: Optional[str] = None  # set when replying
    in_reply_to: Optional[str] = None  # RFC822 Message-Id of the message being replied to
    send_at: Optional[str] = None  # ISO 8601, for scheduled send


class TurnRequest(BaseModel):
    session_id: str = Field(min_length=1)
    transcript: str = ""


class TurnResponse(BaseModel):
    speech: str  # THE string the client speaks. Never empty.
    phase: Phase = "idle"
    draft: Optional[Draft] = None  # optional on-screen display only
    awaiting_confirmation: bool = False
    listen_again: bool = True  # hint: reopen the mic after speaking
    ok: bool = True  # false = this turn failed; speech explains it
    focus_target: Optional[str] = None  # element id the frontend should focus() (F30)


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
