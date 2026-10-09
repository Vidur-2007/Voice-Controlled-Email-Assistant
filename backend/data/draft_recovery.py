"""F56 — draft recovery after a crash or reload (PHASE_10_PLUS_SPEC.md
§13.2).

Deliberately holds no session id — a single-row table, "the current
recoverable draft," is all a single-user local app needs; see
routes/voice.py's _persist_recoverable_draft() docstring for why.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.data.store import get_connection
from backend.models import Draft

RECOVERY_WINDOW_HOURS = 12


def persist_recoverable_draft(draft: Draft) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO recoverable_draft (id, draft_json, updated_at) VALUES (1, ?, ?)",
        (draft.model_dump_json(), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def clear_recoverable_draft() -> None:
    """Privacy rule (§13.2): discarding must actually delete the row, not
    just mark it inactive.
    """
    conn = get_connection()
    conn.execute("DELETE FROM recoverable_draft WHERE id = 1")
    conn.commit()


def get_recoverable_draft() -> Optional[Draft]:
    """None if nothing is stored, or if what's stored is older than
    RECOVERY_WINDOW_HOURS — a stale row found this way is deleted on the
    spot (the same real-delete privacy rule above, just triggered by age
    instead of an explicit discard).
    """
    conn = get_connection()
    row = conn.execute("SELECT draft_json, updated_at FROM recoverable_draft WHERE id = 1").fetchone()
    if row is None:
        return None

    draft_json, updated_at = row
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        clear_recoverable_draft()
        return None

    if datetime.now(timezone.utc) - updated > timedelta(hours=RECOVERY_WINDOW_HOURS):
        clear_recoverable_draft()
        return None

    return Draft.model_validate_json(draft_json)
