"""File attachments (F30) — saving an uploaded file, and remembering the
most recently uploaded one per session for "attach the last document I
mentioned".

The "last attachment" pointer lives in a plain module-level dict, NOT on
`ConversationState` — `reset_session()` replaces the whole
`ConversationState` object on send/save-draft/cancel/restart, and
ATTACH_LAST's entire value is reusing a file across *multiple* emails in
one browser session (draft #1 attaches invoice.pdf and is sent; draft #2
says "attach the last document I mentioned" and reuses it). Tying the
pointer to `ConversationState`'s lifecycle would break that on every
reset.

Uploaded files are deliberately NOT auto-deleted anywhere in this phase —
a known, accepted limitation for this local single-user app (see the
Phase 7 plan's "Attachment lifecycle" note). A future phase could add a
startup sweep of attachment directories older than N days.
"""

from pathlib import Path

from backend.config import get_settings

_last_attachment: dict[str, str] = {}


def _session_dir(session_id: str) -> Path:
    return Path(get_settings().attachments_dir) / session_id


def save_attachment(session_id: str, filename: str, data: bytes) -> str:
    """Writes under <attachments_dir>/<session_id>/<filename>, returns the
    full path (stored directly in Draft.attachments, so send.py needs no
    extra path reconstruction — Path(p).name recovers the display name).
    Also records this as the session's most recent attachment.
    """
    directory = _session_dir(session_id)
    directory.mkdir(parents=True, exist_ok=True)
    # A bare filename (no directory components) — Path(filename).name
    # strips any that snuck in, so an upload can never write outside its
    # own session directory.
    safe_name = Path(filename).name or "attachment"
    path = directory / safe_name
    path.write_bytes(data)

    full_path = str(path)
    _last_attachment[session_id] = full_path
    return full_path


def get_last_attachment(session_id: str) -> str:
    """Returns "" if nothing has been attached yet this session, or if the
    file has since been removed from disk.
    """
    path = _last_attachment.get(session_id, "")
    if path and Path(path).exists():
        return path
    return ""


def set_last_attachment(session_id: str, path: str) -> None:
    _last_attachment[session_id] = path


def reset_attachments_for_tests() -> None:
    """Wired into tests/conftest.py's autouse fixture, same pattern as the
    fake inbox reset — clears the in-memory "last attachment" pointer
    between tests. Files on disk are handled separately by the fixture
    (ATTACHMENTS_DIR is test-isolated, same pattern as OUTBOX_PATH).
    """
    _last_attachment.clear()
