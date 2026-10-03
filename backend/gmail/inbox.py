"""Public inbox entry points — list/read/archive/mark-read (Phase 6, F22,
F36, F38-F41). Dispatches fake vs real per settings.fake_gmail, same
pattern as send.py.

list_unread()/get_thread_context() are allowed to raise (a real Gmail
failure, or SpokenError) rather than returning a MailResult — routes/voice.py
already has a top-level try/except that maps any exception to spoken text
(A5), and there's no natural "success" value for a list/read call the way
there is for send/archive. archive() DOES return a MailResult, matching
send.py's _real_send style, since "archived, but here's why it failed" is
exactly that shape. mark_read() returns None and is allowed to raise on
real failure — the caller decides whether that failure IS the turn's whole
answer (the explicit "mark as read" command) or something to swallow so it
never masks a bigger answer (the implicit mark-read inside summarize/read
full).
"""

import base64
import re

from googleapiclient.discovery import build

from backend.config import get_settings
from backend.errors import to_spoken
from backend.gmail import auth, fake
from backend.models import InboxItem, MailResult, ThreadContext

_UNREAD_LABELS = ["UNREAD", "INBOX"]


def _build_service():
    creds = auth.get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_body(body: dict) -> str:
    data = body.get("data")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _extract_plain_text(payload: dict) -> str:
    """Walk a Gmail message payload for its readable text.

    Resolves plain-vs-HTML independently at EACH multipart/alternative
    node, then concatenates across every other part — a global "prefer
    plain text anywhere in the message" rule would silently drop a second,
    HTML-only multipart/alternative branch (e.g. quoted history) just
    because an earlier branch happened to have plain text (Phase 6 bug #3).
    """
    mime_type = payload.get("mimeType", "")
    parts = payload.get("parts")

    if not parts:
        if mime_type == "text/plain":
            return _decode_body(payload.get("body", {}))
        if mime_type == "text/html":
            return _strip_html(_decode_body(payload.get("body", {})))
        return ""

    if mime_type == "multipart/alternative":
        plain = ""
        html = ""
        for part in parts:
            part_mime = part.get("mimeType", "")
            if part_mime == "text/plain" and not part.get("parts"):
                plain = _decode_body(part.get("body", {}))
            elif part_mime == "text/html" and not part.get("parts"):
                html = _decode_body(part.get("body", {}))
            else:
                nested = _extract_plain_text(part)
                if nested and not plain:
                    plain = nested
        return plain or _strip_html(html)

    texts = [_extract_plain_text(part) for part in parts]
    return "\n\n".join(t for t in texts if t)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _parse_sender(from_header: str) -> tuple[str, str]:
    """'Priya Nair <priya.nair@example.com>' -> ('Priya Nair', 'priya.nair@example.com')."""
    from_header = from_header.strip()
    if "<" in from_header and from_header.endswith(">"):
        name, _, addr = from_header.rpartition("<")
        return name.strip().strip('"'), addr.rstrip(">").strip()
    return from_header, from_header


def list_unread(limit: int = 10) -> list[InboxItem]:
    settings = get_settings()
    if settings.fake_gmail:
        return fake.fake_list_unread(limit)

    service = _build_service()
    listing = (
        service.users()
        .messages()
        .list(userId="me", labelIds=_UNREAD_LABELS, maxResults=limit)
        .execute()
    )
    message_ids = [m["id"] for m in listing.get("messages", [])]

    items: list[InboxItem] = []
    for message_id in message_ids:
        msg = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
                metadataHeaders=["From", "Subject"],
            )
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        sender_name, sender_email = _parse_sender(_header(headers, "From"))
        items.append(
            InboxItem(
                id=msg["id"],
                thread_id=msg.get("threadId", ""),
                sender_name=sender_name,
                sender_email=sender_email,
                subject=_header(headers, "Subject"),
                snippet=msg.get("snippet", ""),
                unread=True,
            )
        )
    return items


def get_thread_context(thread_id: str) -> ThreadContext:
    settings = get_settings()
    if settings.fake_gmail:
        return fake.fake_get_thread_context(thread_id)

    service = _build_service()
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    messages = thread.get("messages", [])
    if not messages:
        return ThreadContext(text="", last_message_id_header=None)

    texts = []
    for msg in messages:
        payload = msg.get("payload", {})
        text = _extract_plain_text(payload)
        if text:
            texts.append(text)

    last_headers = messages[-1].get("payload", {}).get("headers", [])
    last_message_id_header = _header(last_headers, "Message-Id") or None

    return ThreadContext(text="\n\n---\n\n".join(texts), last_message_id_header=last_message_id_header)


def get_thread_text(thread_id: str) -> str:
    return get_thread_context(thread_id).text


def archive(message_id: str) -> MailResult:
    settings = get_settings()
    if settings.fake_gmail:
        return fake.fake_archive(message_id)

    try:
        service = _build_service()
        service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()
    except Exception as exc:  # noqa: BLE001 - every Gmail failure must be spoken (A5)
        return MailResult(success=False, message=to_spoken(exc))

    return MailResult(success=True, message="Archived.")


def mark_read(message_id: str) -> None:
    settings = get_settings()
    if settings.fake_gmail:
        fake.fake_mark_read(message_id)
        return

    service = _build_service()
    service.users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()
