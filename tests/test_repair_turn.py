"""F54 — one dedicated route-level test per `repair_turn` reason
(PHASE_10_PLUS_SPEC.md §10.2), asserting the exact `reason` string lands in
the events table, not just that some row appeared.
"""

import json

from backend.data.store import get_connection


def _repair_reasons(session_id: str) -> list[str]:
    rows = get_connection().execute(
        "SELECT detail FROM events WHERE session_id = ? AND event = 'repair_turn'", (session_id,)
    ).fetchall()
    return [json.loads(r[0])["reason"] for r in rows]


def test_self_correction_reason(client):
    session_id = "repair-self-correction"
    client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "transcript": "tell John Smith I will be there at 5, no wait, I'll be there at 6",
        },
    )
    assert "self_correction" in _repair_reasons(session_id)


def test_undo_reason(client):
    session_id = "repair-undo"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "make it shorter"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "undo"})
    assert "undo" in _repair_reasons(session_id)


def test_redo_reason(client):
    session_id = "repair-redo"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "make it shorter"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "undo"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "redo"})
    assert "redo" in _repair_reasons(session_id)


def test_start_over_reason(client):
    session_id = "repair-start-over"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "start over"})
    assert "start_over" in _repair_reasons(session_id)


def test_reclarify_reason(client):
    session_id = "repair-reclarify"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "email John about the budget"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "banana"})
    assert "reclarify" in _repair_reasons(session_id)


def test_late_edit_reason(client):
    session_id = "repair-late-edit"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "make it shorter"})
    assert "late_edit" in _repair_reasons(session_id)
