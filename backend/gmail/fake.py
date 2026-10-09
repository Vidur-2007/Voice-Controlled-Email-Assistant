"""FAKE_GMAIL backend — writes to outbox.jsonl instead of calling the real API.

Every /api/mail/* style operation returns a MailResult, success or not —
callers never need to branch on an exception or a status code (§21).
"""

import json
from datetime import datetime, timezone

from backend.config import get_settings
from backend.models import Draft, InboxItem, MailResult, ThreadContext

_INVALID_RECIPIENT_MESSAGE = (
    "That address doesn't look right, so I haven't sent it. "
    "Say 'change recipient' to fix it."
)


def _is_valid_recipient(address: str) -> bool:
    return bool(address) and "@" in address


def _record(draft: Draft, kind: str) -> dict:
    return {
        "type": kind,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "recipient": draft.recipient,
        "cc": draft.cc,
        "bcc": draft.bcc,
        "subject": draft.subject,
        "body": draft.body,
        "thread_id": draft.thread_id,
        "attachments": draft.attachments,
        "send_at": draft.send_at,
    }


def _append_line(record: dict) -> None:
    path = get_settings().outbox_path
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def fake_send(draft: Draft) -> MailResult:
    if not _is_valid_recipient(draft.recipient):
        return MailResult(success=False, message=_INVALID_RECIPIENT_MESSAGE)

    _append_line(_record(draft, "send"))
    who = draft.recipient_name or draft.recipient
    return MailResult(success=True, message=f"Sent to {who}.")


def fake_save_draft(draft: Draft) -> MailResult:
    if not _is_valid_recipient(draft.recipient):
        return MailResult(success=False, message=_INVALID_RECIPIENT_MESSAGE)

    _append_line(_record(draft, "draft"))
    return MailResult(success=True, message="Saved as a draft.")


# ---------------------------------------------------------------------------
# Fake inbox (Phase 6) — a fixed 3-message seed, offline stand-in for a real
# Gmail inbox. Read/archived state is tracked separately from the seed data
# itself, so reset_fake_inbox_for_tests() can restore a clean slate without
# re-literal-ing the messages.
# ---------------------------------------------------------------------------

# The fixed fake "authenticated account" address — used for self-exclusion
# in fake-mode reply-all, mirroring what a real get_my_email() (gmail/auth.py)
# returns via a real getProfile() call.
_FAKE_MY_EMAIL = "me@example.com"

_FAKE_INBOX_SEED = [
    {
        "id": "fake-msg-1",
        "thread_id": "fake-thread-1",
        "sender_name": "Priya Nair",
        "sender_email": "priya.nair@example.com",
        "subject": "Project update",
        "snippet": "Just wanted to give you a quick update on where things stand.",
        "body": (
            "Hi,\n\nJust wanted to give you a quick update on where things stand with "
            "the project. We're on track for Friday, and the numbers from last week "
            "look good.\n\nThanks,\nPriya"
        ),
        "message_id_header": "<fake-msg-1@example.com>",
        "to": [_FAKE_MY_EMAIL],
        "cc": [],
    },
    {
        "id": "fake-msg-2",
        "thread_id": "fake-thread-2",
        "sender_name": "David Chen",
        "sender_email": "david.chen@example.com",
        "subject": "Lunch on Thursday?",
        "snippet": "Are you free for lunch this Thursday around noon?",
        "body": (
            "Hey,\n\nAre you free for lunch this Thursday around noon? There's a new "
            "place near the office I've been wanting to try.\n\nDavid"
        ),
        "message_id_header": "<fake-msg-2@example.com>",
        # A non-trivial CC list specifically so reply-all has something real
        # to test: excludes David (the sender, already becoming "To") and
        # _FAKE_MY_EMAIL (self), leaving Sarah Lee + Alex Kim.
        "to": [_FAKE_MY_EMAIL],
        "cc": ["sarah.lee@example.com", "alex.kim@example.com"],
    },
    {
        "id": "fake-msg-3",
        "thread_id": "fake-thread-3",
        "sender_name": "Support Team",
        "sender_email": "support@example.com",
        "subject": "Your subscription receipt",
        "snippet": "Thanks for your payment. Here is your receipt for this month.",
        "body": (
            "Thanks for your payment. Here is your receipt for this month. Your next "
            "payment will be charged automatically."
        ),
        "message_id_header": "<fake-msg-3@example.com>",
        "to": [_FAKE_MY_EMAIL],
        "cc": [],
    },
]

# id -> {"unread": bool, "archived": bool}, reset alongside the seed data.
_fake_inbox_state: dict[str, dict] = {}


def _reset_state() -> None:
    _fake_inbox_state.clear()
    for msg in _FAKE_INBOX_SEED:
        _fake_inbox_state[msg["id"]] = {"unread": True, "archived": False}


_reset_state()


def reset_fake_inbox_for_tests() -> None:
    """Wired into tests/conftest.py's autouse fixture, same pattern as the
    contacts DB reseed — every test starts with a clean 3-message inbox.
    """
    _reset_state()


def fake_list_unread(limit: int) -> list[InboxItem]:
    items = []
    for msg in _FAKE_INBOX_SEED:
        state = _fake_inbox_state[msg["id"]]
        if state["archived"] or not state["unread"]:
            continue
        items.append(
            InboxItem(
                id=msg["id"],
                thread_id=msg["thread_id"],
                sender_name=msg["sender_name"],
                sender_email=msg["sender_email"],
                subject=msg["subject"],
                snippet=msg["snippet"],
                unread=True,
            )
        )
        if len(items) >= limit:
            break
    return items


def fake_search(fields, limit: int) -> list[InboxItem]:
    """F55 — case-insensitive substring match against the fixed seed
    (not scoped to unread, unlike fake_list_unread — a search isn't "my
    unread inbox"). `after`/`before` are ignored in fake mode (§13.1's
    fake-parsing scope limit, see ai/search_query.py).
    """
    sender_needle = (fields.sender or "").strip().lower()
    subject_needle = (fields.subject_terms or "").strip().lower()

    items = []
    for msg in _FAKE_INBOX_SEED:
        state = _fake_inbox_state[msg["id"]]
        if state["archived"]:
            continue
        if sender_needle and sender_needle not in msg["sender_name"].lower() and sender_needle not in msg["sender_email"].lower():
            continue
        if subject_needle and subject_needle not in msg["subject"].lower():
            continue
        items.append(
            InboxItem(
                id=msg["id"],
                thread_id=msg["thread_id"],
                sender_name=msg["sender_name"],
                sender_email=msg["sender_email"],
                subject=msg["subject"],
                snippet=msg["snippet"],
                unread=state["unread"],
            )
        )
        if len(items) >= limit:
            break
    return items


def fake_get_thread_context(thread_id: str) -> ThreadContext:
    for msg in _FAKE_INBOX_SEED:
        if msg["thread_id"] == thread_id:
            return ThreadContext(
                text=msg["body"],
                last_message_id_header=msg["message_id_header"],
                to_recipients=list(msg["to"]),
                cc_recipients=list(msg["cc"]),
            )
    return ThreadContext(text="", last_message_id_header=None)


def fake_get_my_email() -> str:
    return _FAKE_MY_EMAIL


def fake_archive(message_id: str) -> MailResult:
    state = _fake_inbox_state.get(message_id)
    if state is None:
        return MailResult(success=False, message="I couldn't find that message.")
    state["archived"] = True
    return MailResult(success=True, message="Archived.")


def fake_mark_read(message_id: str) -> None:
    state = _fake_inbox_state.get(message_id)
    if state is not None:
        state["unread"] = False
