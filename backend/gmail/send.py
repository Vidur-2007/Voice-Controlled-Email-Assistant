"""Public send / save-draft entry points. Dispatches fake vs real per
settings.fake_gmail (§5). F33, F34.

Real Gmail errors route through the existing backend/errors.py catch-all
(to_spoken), not a bypass — its pattern table (credentials.json, 401/403,
429/5xx, invalid_grant) was written for exactly this shape of exception,
and confirmed (by reading the installed googleapiclient/google-auth
source) to actually match: HttpError's str() embeds the raw numeric
status code, and a revoked/expired-token RefreshError's str() reliably
contains "invalid_grant".
"""

import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path

from googleapiclient.discovery import build

from backend.config import get_settings
from backend.errors import to_spoken
from backend.gmail import auth, fake
from backend.models import Draft, MailResult

_INVALID_RECIPIENT_MESSAGE = (
    "That address doesn't look right, so I haven't sent it. "
    "Say 'change recipient' to fix it."
)


def send_email(draft: Draft) -> MailResult:
    settings = get_settings()
    if settings.fake_gmail:
        return fake.fake_send(draft)
    return _real_send(draft)


def save_draft(draft: Draft) -> MailResult:
    settings = get_settings()
    if settings.fake_gmail:
        return fake.fake_save_draft(draft)
    return _real_save_draft(draft)


def _is_valid_recipient(address: str) -> bool:
    return bool(address) and "@" in address


def _build_message_payload(draft: Draft) -> dict:
    """The exact construction from the spec's Phase 5 section: set_content
    (not set_payload), and threadId as a SIBLING of raw — nesting it
    inside the message dict instead is the common bug the spec calls out.
    """
    msg = EmailMessage()
    msg["To"] = draft.recipient
    msg["Subject"] = draft.subject
    if draft.cc:
        msg["Cc"] = ", ".join(draft.cc)
    if draft.bcc:
        msg["Bcc"] = ", ".join(draft.bcc)
    if draft.in_reply_to:
        # Gmail only threads a reply when threadId, In-Reply-To/References,
        # AND Subject all agree (Phase 6 bug #1) — threadId alone (the only
        # thing Phase 5 ever set) is not enough.
        msg["In-Reply-To"] = draft.in_reply_to
        msg["References"] = draft.in_reply_to
    msg.set_content(draft.body)

    for path in draft.attachments:
        _add_attachment(msg, path)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    payload = {"raw": raw}
    if draft.thread_id:
        payload["threadId"] = draft.thread_id  # sibling of raw, NOT nested inside it
    return payload


def _add_attachment(msg: EmailMessage, path: str) -> None:
    """F30: `set_content()` (plain body) + `add_attachment()` produces a
    correct `multipart/mixed` message — verified directly against the
    installed `email.message.EmailMessage`. `mimetypes.guess_type()`
    returns `(None, None)` for an unrecognized extension; fall back to
    `application/octet-stream` rather than let that raise.
    """
    data = Path(path).read_bytes()
    guessed, _encoding = mimetypes.guess_type(path)
    maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
    msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=Path(path).name)


def _build_service():
    creds = auth.get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _real_send(draft: Draft) -> MailResult:
    if not _is_valid_recipient(draft.recipient):
        return MailResult(success=False, message=_INVALID_RECIPIENT_MESSAGE)
    try:
        service = _build_service()
        payload = _build_message_payload(draft)
        service.users().messages().send(userId="me", body=payload).execute()
    except Exception as exc:  # noqa: BLE001 - every Gmail failure must be spoken (A5)
        return MailResult(success=False, message=to_spoken(exc))

    who = draft.recipient_name or draft.recipient
    return MailResult(success=True, message=f"Sent to {who}.")


def _real_save_draft(draft: Draft) -> MailResult:
    if not _is_valid_recipient(draft.recipient):
        return MailResult(success=False, message=_INVALID_RECIPIENT_MESSAGE)
    try:
        service = _build_service()
        payload = _build_message_payload(draft)
        # Drafts nest one level deeper than a direct send — the payload
        # (raw + threadId) is wrapped in {"message": ...}.
        service.users().drafts().create(userId="me", body={"message": payload}).execute()
    except Exception as exc:  # noqa: BLE001
        return MailResult(success=False, message=to_spoken(exc))

    return MailResult(success=True, message="Saved as a draft.")
