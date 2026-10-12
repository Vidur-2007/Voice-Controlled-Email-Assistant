"""Public saved-drafts entry points — list/send a previously saved Gmail
draft (Phase 15: "read my drafts" / "send my saved draft"). Dispatches
fake vs real per settings.fake_gmail, same pattern as send.py/inbox.py.
"""

from email.utils import getaddresses

from googleapiclient.discovery import build

from backend.config import get_settings
from backend.errors import to_spoken
from backend.gmail import auth, fake
from backend.models import DraftSummary, MailResult


def _build_service():
    creds = auth.get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _parse_recipient(to_header: str) -> tuple[str, str]:
    """'Priya Nair <priya.nair@example.com>' -> ('Priya Nair',
    'priya.nair@example.com'); handles a quoted comma in the display
    name the same way gmail/inbox.py's reply-all address parsing does.
    Only the first "To" address is used — a saved draft's own recipient,
    for the spoken listing, not every CC.
    """
    pairs = getaddresses([to_header]) if to_header else []
    if not pairs:
        return "", ""
    name, addr = pairs[0]
    return name.strip().strip('"'), addr.strip()


def list_drafts(limit: int = 10) -> list[DraftSummary]:
    settings = get_settings()
    if settings.fake_gmail:
        return fake.fake_list_drafts(limit)

    service = _build_service()
    listing = service.users().drafts().list(userId="me", maxResults=limit).execute()
    draft_ids = [d["id"] for d in listing.get("drafts", [])]

    items: list[DraftSummary] = []
    for draft_id in draft_ids:
        draft = (
            service.users()
            .drafts()
            .get(userId="me", id=draft_id, format="metadata")
            .execute()
        )
        message = draft.get("message", {})
        headers = message.get("payload", {}).get("headers", [])
        name, email = _parse_recipient(_header(headers, "To"))
        items.append(
            DraftSummary(
                id=draft_id,
                recipient_name=name,
                recipient_email=email,
                subject=_header(headers, "Subject"),
                snippet=message.get("snippet", ""),
            )
        )
    return items


def send_draft(draft_id: str) -> MailResult:
    settings = get_settings()
    if settings.fake_gmail:
        return fake.fake_send_draft(draft_id)

    try:
        service = _build_service()
        service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    except Exception as exc:  # noqa: BLE001 - every Gmail failure must be spoken (A5)
        return MailResult(success=False, message=to_spoken(exc))

    return MailResult(success=True, message="Sent.")
