"""Send, draft, auth, inbox — /api/mail/* (§21). Direct access for testing
without the frontend/session machinery, same pattern as routes/draft.py.

Every /api/mail/* route returns HTTP 200 with a MailResult (or plain data
for the read-only inbox routes), even on failure — never a 4xx/5xx body.
The client never branches on a status code.
"""

from fastapi import APIRouter, File, Form, UploadFile

from backend.attachments import save_attachment
from backend.errors import SpokenError, to_spoken
from backend.gmail import auth
from backend.gmail.inbox import archive, get_thread_context, list_unread
from backend.gmail.schedule import schedule_send
from backend.gmail.send import save_draft, send_email
from backend.models import Draft, InboxItem, MailResult, ThreadContext
from backend.session import get_session

router = APIRouter()


@router.post("/mail/send", response_model=MailResult)
def mail_send(draft: Draft) -> MailResult:
    return send_email(draft)


@router.post("/mail/draft", response_model=MailResult)
def mail_draft(draft: Draft) -> MailResult:
    return save_draft(draft)


@router.post("/mail/auth", response_model=MailResult)
def mail_auth() -> MailResult:
    """Runs the blocking OAuth flow (a real browser window opens). A
    deliberate, separate, developer-run step — never triggered inline
    from a voice turn (see backend/gmail/auth.py's module docstring).
    """
    try:
        auth.connect()
    except SpokenError as exc:
        return MailResult(success=False, message=to_spoken(exc))
    except Exception as exc:  # noqa: BLE001 - never fail silently (A5)
        return MailResult(success=False, message=to_spoken(exc))
    return MailResult(success=True, message="Your email is connected.")


@router.get("/mail/inbox", response_model=list[InboxItem])
def mail_inbox(limit: int = 10) -> list[InboxItem]:
    return list_unread(limit=limit)


@router.get("/mail/thread/{thread_id}", response_model=ThreadContext)
def mail_thread(thread_id: str) -> ThreadContext:
    return get_thread_context(thread_id)


@router.post("/mail/archive/{message_id}", response_model=MailResult)
def mail_archive(message_id: str) -> MailResult:
    return archive(message_id)


@router.post("/mail/schedule", response_model=MailResult)
def mail_schedule(draft: Draft) -> MailResult:
    """F35, §21's route table — direct-testing endpoint. `draft.send_at`
    must already be a resolved ISO timestamp; the voice-driven flow
    (routes/voice.py) resolves a spoken time phrase before calling the
    same schedule_send() this wraps.
    """
    return schedule_send(draft)


@router.post("/mail/attachment", response_model=MailResult)
def mail_attachment(session_id: str = Form(...), file: UploadFile = File(...)) -> MailResult:
    """F30 — a file can never flow through a speech transcript, so this is
    a second, deliberate entry point outside /api/turn that appends
    directly to the session's draft (see the Phase 7 plan's F30 note on
    why voice can't drive this itself: no way to open a real OS file
    picker from a voice-turn response, a genuine browser user-activation
    constraint, not an oversight).
    """
    data = file.file.read()  # sync read — this handler is plain def, no await
    path = save_attachment(session_id, file.filename or "attachment", data)

    state = get_session(session_id)
    state.draft.attachments.append(path)

    return MailResult(success=True, message=f"Attached {file.filename or 'the file'}.")
