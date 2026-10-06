"""F54 privacy rule (PHASE_10_PLUS_SPEC.md §10.2) — end-to-end proof, not
just a unit test of log_event() in isolation: a full scripted conversation
containing distinctive, never-otherwise-appearing strings must leave no
trace of them in the events table under the default LOG_CONTENT=0, and
must show them under LOG_CONTENT=1 — proving the gate actually gates
something rather than merely defaulting to off.
"""

from backend.config import get_settings
from backend.data.store import get_connection

_PROBE_RECIPIENT = "tell Zzyzx Testcontact"
_PROBE_BODY_WORD = "XYZZYPROBESTRING"


def _all_event_rows(session_id: str) -> list[str]:
    rows = get_connection().execute(
        "SELECT session_id, ts, event, phase, ms, detail FROM events WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    return [str(row) for row in rows]


def test_log_content_off_leaves_no_trace_of_real_content(client):
    assert get_settings().log_content is False  # the test-suite default
    session_id = "privacy-off"

    client.post(
        "/api/turn",
        json={"session_id": session_id, "transcript": f"{_PROBE_RECIPIENT} {_PROBE_BODY_WORD}"},
    )
    client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})

    rows = _all_event_rows(session_id)
    assert rows  # the conversation actually happened and logged something
    blob = "\n".join(rows)
    assert "Zzyzx" not in blob
    assert _PROBE_BODY_WORD not in blob


def test_log_content_on_captures_real_content(client, monkeypatch):
    monkeypatch.setenv("LOG_CONTENT", "1")
    get_settings.cache_clear()
    try:
        session_id = "privacy-on"
        client.post(
            "/api/turn",
            json={"session_id": session_id, "transcript": f"{_PROBE_RECIPIENT} {_PROBE_BODY_WORD}"},
        )
        client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})

        rows = _all_event_rows(session_id)
        blob = "\n".join(rows)
        assert _PROBE_BODY_WORD in blob
    finally:
        monkeypatch.delenv("LOG_CONTENT", raising=False)
        get_settings.cache_clear()
