"""F54 instrumentation — backend/events.py unit tests (PHASE_10_PLUS_SPEC.md
§10.2). Offline only; writes go to the real (in-memory, per conftest.py)
events table so round-tripping is checked against actual rows, not mocks.
"""

import json

import pytest

from backend.config import get_settings
from backend.data.store import get_connection
from backend.events import categorize_error, classify_repair_turn, log_event


def _rows_for(session_id: str) -> list[tuple]:
    conn = get_connection()
    return conn.execute(
        "SELECT event, phase, ms, detail FROM events WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()


def test_classify_repair_turn_each_reason():
    assert classify_repair_turn(self_corrected=True) == "self_correction"
    assert classify_repair_turn(undo=True) == "undo"
    assert classify_repair_turn(redo=True) == "redo"
    assert classify_repair_turn(start_over=True) == "start_over"
    assert classify_repair_turn(reclarify=True) == "reclarify"
    assert classify_repair_turn(late_edit=True) == "late_edit"


def test_classify_repair_turn_no_signal_is_none():
    assert classify_repair_turn() is None


def test_log_event_round_trips_detail():
    log_event("events-1", "turn_start", phase="idle", ms=12, detail={"transcript_words": 3})
    rows = _rows_for("events-1")
    assert len(rows) == 1
    event, phase, ms, detail_raw = rows[0]
    assert event == "turn_start"
    assert phase == "idle"
    assert ms == 12
    assert json.loads(detail_raw) == {"transcript_words": 3}


def test_log_event_content_dropped_when_log_content_off():
    assert get_settings().log_content is False  # the test-suite default
    log_event("events-2", "draft_created", detail={"mode": "brief"}, content={"body": "secret body"})
    rows = _rows_for("events-2")
    detail = json.loads(rows[0][3])
    assert detail == {"mode": "brief"}
    assert "secret body" not in rows[0][3]


def test_log_event_content_persisted_when_log_content_on(monkeypatch):
    monkeypatch.setenv("LOG_CONTENT", "1")
    get_settings.cache_clear()
    try:
        log_event("events-3", "draft_created", detail={"mode": "brief"}, content={"body": "secret body"})
        rows = _rows_for("events-3")
        detail = json.loads(rows[0][3])
        assert detail == {"mode": "brief", "body": "secret body"}
    finally:
        monkeypatch.delenv("LOG_CONTENT", raising=False)
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "speech,expected",
    [
        ("I can't send mail yet because the email credentials file is missing, so nothing was sent.", "missing_credentials"),
        ("My access to your email has expired, so nothing was sent.", "auth_expired"),
        ("Your email account refused the request, so nothing was sent.", "auth_refused"),
        ("Your email provider is busy right now, so nothing was sent.", "provider_busy"),
        ("That address doesn't look right, so I haven't sent it.", "invalid_recipient"),
        ("I can't write the email because the writing assistant isn't set up, so nothing was sent.", "llm_not_configured"),
        ("I couldn't reach the internet, so nothing was sent.", "network_down"),
        ("I couldn't write that properly, so nothing was sent.", "llm_validation_failed"),
        ("That's taking too long to write, so nothing has been sent yet.", "llm_timeout"),
        ("The writing assistant ran into a problem, so nothing was sent.", "llm_error"),
        ("I didn't catch that. Could you say it again?", "empty_transcript"),
        ("I haven't read the message back to you yet.", "send_too_early"),
        ("Something completely unrecognized happened.", "other"),
    ],
)
def test_categorize_error_maps_known_messages(speech, expected):
    assert categorize_error(speech) == expected
