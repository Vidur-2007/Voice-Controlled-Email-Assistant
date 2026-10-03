"""Offline tests for backend/gmail/schedule.py (F35). No network calls —
`run_due_scheduled_sends()` is called directly, never via the real
background thread (TestClient(app) used without `with`, as this repo's
`client` fixture does, never triggers ASGI lifespan).
"""

from datetime import datetime

from backend.data.store import get_connection
from backend.gmail.schedule import parse_schedule_time, run_due_scheduled_sends, schedule_send
from backend.models import Draft

_NOW = datetime(2026, 9, 28, 14, 30, 0)  # a Monday, 2:30 PM


# ---------------------------------------------------------------------------
# parse_schedule_time
# ---------------------------------------------------------------------------


def test_bare_hour_pm():
    r = parse_schedule_time("5pm", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 28, 17, 0, 0)


def test_hour_and_minutes_with_space_before_ampm():
    r = parse_schedule_time("5:30 pm", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 28, 17, 30, 0)


def test_noon():
    r = parse_schedule_time("noon", now=datetime(2026, 9, 28, 8, 0, 0))
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 28, 12, 0, 0)
    assert r.rolled_to_tomorrow is False


def test_midnight():
    r = parse_schedule_time("midnight", now=datetime(2026, 9, 28, 8, 0, 0))
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 29, 0, 0, 0)


def test_tomorrow_at_time():
    r = parse_schedule_time("tomorrow at 9am", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 29, 9, 0, 0)
    assert r.is_tomorrow is True
    assert r.rolled_to_tomorrow is False


def test_today_at_future_time():
    r = parse_schedule_time("today at 6pm", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 28, 18, 0, 0)


def test_explicit_today_already_passed_is_rejected_not_rolled():
    r = parse_schedule_time("today at 1pm", now=_NOW)
    assert r.status == "invalid"
    assert "already passed" in r.message


def test_bare_time_already_passed_rolls_to_tomorrow_with_disclosure():
    r = parse_schedule_time("1pm", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 29, 13, 0, 0)
    assert r.rolled_to_tomorrow is True


def test_unambiguous_24_hour_format():
    r = parse_schedule_time("17:00", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 28, 17, 0, 0)


def test_ambiguous_bare_hour_asks_instead_of_guessing():
    r = parse_schedule_time("5", now=_NOW)
    assert r.status == "ambiguous"
    assert "5 AM" in r.message and "5 PM" in r.message


def test_in_n_minutes():
    r = parse_schedule_time("in 30 minutes", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 28, 15, 0, 0)


def test_in_n_hours():
    r = parse_schedule_time("in 2 hours", now=_NOW)
    assert r.status == "resolved"
    assert r.when == datetime(2026, 9, 28, 16, 30, 0)


def test_unparseable_phrase_is_invalid():
    r = parse_schedule_time("garbage", now=_NOW)
    assert r.status == "invalid"


def test_out_of_range_hour_is_invalid():
    r = parse_schedule_time("25:00", now=_NOW)
    assert r.status == "invalid"


# ---------------------------------------------------------------------------
# schedule_send / run_due_scheduled_sends
# ---------------------------------------------------------------------------


def _draft(send_at: str) -> Draft:
    return Draft(
        recipient="john.smith@example.com",
        recipient_name="John Smith",
        subject="Hi",
        body="See you then.",
        send_at=send_at,
    )


def test_schedule_send_writes_a_row():
    result = schedule_send(_draft("2026-09-28T17:00:00"))
    assert result.success is True

    conn = get_connection()
    rows = conn.execute("SELECT send_at, sent FROM scheduled WHERE send_at = ?", ("2026-09-28T17:00:00",)).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == 0


def test_schedule_send_invalid_recipient_refused():
    result = schedule_send(Draft(recipient="", subject="Hi", body="x", send_at="2026-09-28T17:00:00"))
    assert result.success is False


def test_schedule_send_missing_time_refused():
    result = schedule_send(Draft(recipient="a@example.com", subject="Hi", body="x"))
    assert result.success is False


def test_run_due_scheduled_sends_picks_up_due_row_and_marks_sent():
    schedule_send(_draft("2026-01-01T00:00:00"))  # far in the past -> due

    results = run_due_scheduled_sends(now=datetime(2026, 9, 28, 14, 30, 0))
    assert len(results) >= 1
    assert any(r.success for r in results)

    conn = get_connection()
    row = conn.execute(
        "SELECT sent FROM scheduled WHERE send_at = ?", ("2026-01-01T00:00:00",)
    ).fetchone()
    assert row[0] == 1


def test_run_due_scheduled_sends_leaves_future_rows_alone():
    schedule_send(_draft("2099-01-01T00:00:00"))  # far in the future -> not due

    run_due_scheduled_sends(now=datetime(2026, 9, 28, 14, 30, 0))

    conn = get_connection()
    row = conn.execute(
        "SELECT sent FROM scheduled WHERE send_at = ?", ("2099-01-01T00:00:00",)
    ).fetchone()
    assert row[0] == 0


def test_run_due_scheduled_sends_bad_row_does_not_kill_the_poller():
    conn = get_connection()
    conn.execute(
        "INSERT INTO scheduled (send_at, draft_json, sent) VALUES (?, ?, 0)",
        ("2020-01-01T00:00:00", "not valid json"),
    )
    conn.commit()

    results = run_due_scheduled_sends(now=datetime(2026, 9, 28, 14, 30, 0))
    assert any(r.success is False for r in results)

    row = conn.execute(
        "SELECT sent FROM scheduled WHERE send_at = ?", ("2020-01-01T00:00:00",)
    ).fetchone()
    assert row[0] == 1  # marked sent even on failure — no infinite retry of a malformed row
