"""F56 — draft recovery (PHASE_10_PLUS_SPEC.md §13.2). No session id is
ever involved — see backend/data/draft_recovery.py's module docstring.
"""

from datetime import datetime, timedelta, timezone

from backend.data.draft_recovery import (
    RECOVERY_WINDOW_HOURS,
    clear_recoverable_draft,
    get_recoverable_draft,
    persist_recoverable_draft,
)
from backend.data.store import get_connection
from backend.models import Draft


def _set_updated_at(hours_ago: float) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    get_connection().execute("UPDATE recoverable_draft SET updated_at = ?", (ts,))
    get_connection().commit()


def test_persist_and_get_round_trip():
    draft = Draft(recipient_name="John Smith", subject="Hi", body="I will be late.")
    persist_recoverable_draft(draft)
    recovered = get_recoverable_draft()
    assert recovered is not None
    assert recovered.recipient_name == "John Smith"
    assert recovered.body == "I will be late."


def test_get_recoverable_draft_none_when_nothing_stored():
    assert get_recoverable_draft() is None


def test_clear_actually_deletes_the_row():
    persist_recoverable_draft(Draft(body="secret draft content"))
    clear_recoverable_draft()
    assert get_recoverable_draft() is None
    rows = get_connection().execute("SELECT * FROM recoverable_draft").fetchall()
    assert rows == []  # a real DELETE, not a soft-clear flag


def test_persisting_again_overwrites_the_single_row():
    persist_recoverable_draft(Draft(body="first"))
    persist_recoverable_draft(Draft(body="second"))
    assert get_recoverable_draft().body == "second"
    rows = get_connection().execute("SELECT COUNT(*) FROM recoverable_draft").fetchall()
    assert rows[0][0] == 1


def test_recovery_window_boundary_just_under_is_recoverable():
    persist_recoverable_draft(Draft(body="still fresh"))
    _set_updated_at(RECOVERY_WINDOW_HOURS - 0.1)
    assert get_recoverable_draft() is not None


def test_recovery_window_boundary_just_over_is_stale_and_deleted():
    persist_recoverable_draft(Draft(body="too old"))
    _set_updated_at(RECOVERY_WINDOW_HOURS + 0.1)
    assert get_recoverable_draft() is None
    rows = get_connection().execute("SELECT * FROM recoverable_draft").fetchall()
    assert rows == []  # staleness also actually deletes the row


# ---------------------------------------------------------------------------
# Route-level: persisted on every awaiting_confirm turn, cleared on
# send/cancel/restart/save_draft/schedule
# ---------------------------------------------------------------------------


def test_persisted_after_fresh_compose(client):
    client.post("/api/turn", json={"session_id": "recover-compose", "transcript": "tell John Smith I will be late"})
    recovered = get_recoverable_draft()
    assert recovered is not None
    assert recovered.recipient_name == "John Smith"


def test_persisted_after_an_edit(client):
    session_id = "recover-edit"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "make it shorter"})
    recovered = get_recoverable_draft()
    body_after_edit = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "read it back"}
    ).json()["draft"]["body"]
    assert recovered.body == body_after_edit


def test_cleared_on_send(client):
    session_id = "recover-send"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    assert get_recoverable_draft() is not None
    client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
    assert get_recoverable_draft() is None


def test_cleared_on_cancel(client):
    session_id = "recover-cancel"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "cancel"})
    assert get_recoverable_draft() is None


def test_cleared_on_restart(client):
    session_id = "recover-restart"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "start over"})
    assert get_recoverable_draft() is None


def test_cleared_on_save_draft(client):
    session_id = "recover-save"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "save as draft"})
    assert get_recoverable_draft() is None


# ---------------------------------------------------------------------------
# "resume" / "discard" and GET /api/draft/recoverable
# ---------------------------------------------------------------------------


def test_resume_with_nothing_stored(client):
    resp = client.post("/api/turn", json={"session_id": "resume-empty", "transcript": "resume"})
    assert resp.json()["speech"] == "There's nothing to resume."


def test_resume_hydrates_a_fresh_session(client):
    persist_recoverable_draft(
        Draft(recipient_name="Sarah Lee", recipient="sarah.lee@example.com", subject="Update", body="Hi Sarah.")
    )
    resp = client.post("/api/turn", json={"session_id": "resume-fresh", "transcript": "resume"})
    body = resp.json()
    assert body["phase"] == "awaiting_confirm"
    assert body["draft"]["recipient_name"] == "Sarah Lee"
    assert "Sarah Lee" in body["speech"]


def test_discard_via_cancel_clears_the_row(client):
    persist_recoverable_draft(Draft(recipient_name="Sarah Lee", body="Hi Sarah."))
    client.post("/api/turn", json={"session_id": "discard-1", "transcript": "discard"})
    assert get_recoverable_draft() is None


def test_get_recoverable_endpoint_shape_when_empty(client):
    resp = client.get("/api/draft/recoverable")
    body = resp.json()
    assert body == {"recoverable": False, "draft": None, "speech": ""}


def test_get_recoverable_endpoint_shape_when_present(client):
    persist_recoverable_draft(Draft(recipient_name="John Smith", body="one two three four five"))
    resp = client.get("/api/draft/recoverable")
    body = resp.json()
    assert body["recoverable"] is True
    assert body["draft"]["recipient_name"] == "John Smith"
    assert "John Smith" in body["speech"]
    assert "5 words" in body["speech"]
