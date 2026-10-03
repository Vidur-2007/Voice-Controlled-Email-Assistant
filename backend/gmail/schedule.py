"""Scheduled send (F35) — parse a spoken time phrase, store it in the
already-existing (but previously unused) `scheduled` table, and dispatch
it later via a background poller (started from main.py's `lifespan`).

Time parsing is a small, dependency-free stdlib parser, never an LLM
call — the offline-mode rule requires every feature to work with zero
network calls under FAKE_AI=1, which rules out routing this through
Ollama. Naive local `datetime` throughout, deliberately not `zoneinfo`:
`ZoneInfo(...)` genuinely raises `ZoneInfoNotFoundError` on Windows without
`tzdata` installed (no system IANA tz database) — verified directly. This
is a single-user local desktop app, so "5pm" always means the machine's
own local wall-clock time anyway; naive datetimes sidestep the footgun
entirely rather than adding a dependency to work around it.

All stored/compared timestamps are seconds-precision, microsecond=0, ISO
strings — kept consistent on both the write side (parse_schedule_time)
and the read side (run_due_scheduled_sends), so the `send_at <= now`
lexicographic comparison in SQL is never subtly thrown off by one side
carrying microseconds and the other not.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from backend.data.store import get_connection
from backend.gmail.send import send_email
from backend.models import Draft, MailResult

_DAY_TIME_RE = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$")
_DURATION_RE = re.compile(r"^in\s+(\d+)\s+(minute|minutes|hour|hours)$")

_INVALID_RECIPIENT_MESSAGE = (
    "That address doesn't look right, so I haven't scheduled it. "
    "Say 'change recipient' to fix it."
)
_NO_TIME_MESSAGE = "I need a time to schedule this for."
_UNPARSEABLE_MESSAGE = (
    "I didn't catch a time there. Say something like 5 PM, or tomorrow at 9 AM."
)


def _is_valid_recipient(address: str) -> bool:
    return bool(address) and "@" in address


@dataclass
class ScheduleParseResult:
    status: Literal["resolved", "ambiguous", "invalid"]
    when: Optional[datetime] = None
    rolled_to_tomorrow: bool = False
    is_tomorrow: bool = False
    message: str = ""  # the clarifying question (ambiguous) or rejection reason (invalid)


def parse_schedule_time(phrase: str, now: Optional[datetime] = None) -> ScheduleParseResult:
    """Handles: "noon"/"midnight", "H", "H:MM", with/without am/pm and
    with/without a space before it, "today at ...", "tomorrow at ...",
    "in N minutes"/"in N hours". A bare hour 1-12 with no am/pm and no
    explicit day word is genuinely ambiguous — asks rather than guesses.
    Hours 13-23 (and 0) are unambiguous 24-hour format, accepted directly.
    """
    now = (now or datetime.now()).replace(microsecond=0)
    remainder = phrase.strip().lower()

    day_offset: Optional[int] = None
    if remainder.startswith("tomorrow"):
        day_offset = 1
        remainder = remainder[len("tomorrow"):].strip()
    elif remainder.startswith("today"):
        day_offset = 0
        remainder = remainder[len("today"):].strip()
    if remainder.startswith("at "):
        remainder = remainder[3:].strip()

    duration_match = _DURATION_RE.match(remainder)
    if duration_match:
        amount = int(duration_match.group(1))
        unit = duration_match.group(2)
        delta = timedelta(minutes=amount) if unit.startswith("minute") else timedelta(hours=amount)
        when = (now + delta).replace(second=0, microsecond=0)
        return ScheduleParseResult(status="resolved", when=when, is_tomorrow=when.date() != now.date())

    if remainder == "noon":
        hour, minute, has_ampm = 12, 0, True
    elif remainder == "midnight":
        hour, minute, has_ampm = 0, 0, True
    else:
        match = _DAY_TIME_RE.match(remainder)
        if not match:
            return ScheduleParseResult(status="invalid", message=_UNPARSEABLE_MESSAGE)
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        ampm = match.group(3)
        if hour > 23 or minute > 59:
            return ScheduleParseResult(status="invalid", message=_UNPARSEABLE_MESSAGE)
        has_ampm = ampm is not None
        if has_ampm:
            if hour == 12:
                hour = 0 if ampm == "am" else 12
            elif ampm == "pm":
                hour += 12
        elif 1 <= hour <= 12:
            return ScheduleParseResult(
                status="ambiguous",
                message=f"Did you mean {hour} AM or {hour} PM?",
            )
        # hour 13-23, or hour == 0 with no am/pm: unambiguous 24-hour
        # format, fall through unchanged.

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if day_offset == 1:
        candidate += timedelta(days=1)
        return ScheduleParseResult(status="resolved", when=candidate, is_tomorrow=True)

    if day_offset == 0:
        if candidate <= now:
            return ScheduleParseResult(
                status="invalid",
                message="That time today has already passed. Say a different time.",
            )
        return ScheduleParseResult(status="resolved", when=candidate)

    # No explicit day word: roll to tomorrow if it's already passed, and
    # say so out loud (A11/A12) — a blind user can't visually double-check
    # what date silently got picked.
    if candidate <= now:
        candidate += timedelta(days=1)
        return ScheduleParseResult(status="resolved", when=candidate, rolled_to_tomorrow=True)
    return ScheduleParseResult(status="resolved", when=candidate)


def schedule_send(draft: Draft) -> MailResult:
    """Writes a row to the already-existing (Phase 0), previously-unused
    `scheduled` table. Real dispatch happens later via
    `run_due_scheduled_sends()`. `draft.send_at` must already be a
    resolved ISO timestamp — this function does no time parsing itself
    (that's `parse_schedule_time()`, used by the voice-driven flow before
    this is called); the direct `/api/mail/schedule` route passes a Draft
    with `send_at` already set by its caller.
    """
    if not _is_valid_recipient(draft.recipient):
        return MailResult(success=False, message=_INVALID_RECIPIENT_MESSAGE)
    if not draft.send_at:
        return MailResult(success=False, message=_NO_TIME_MESSAGE)

    conn = get_connection()
    conn.execute(
        "INSERT INTO scheduled (send_at, draft_json, sent) VALUES (?, ?, 0)",
        (draft.send_at, draft.model_dump_json()),
    )
    conn.commit()

    who = draft.recipient_name or draft.recipient
    return MailResult(success=True, message=f"Scheduled to send to {who}.")


def run_due_scheduled_sends(now: Optional[datetime] = None) -> list[MailResult]:
    """Called by the background poller (main.py's `lifespan`) every
    `settings.scheduler_poll_s` seconds, and directly by tests — this must
    stay independently callable: `TestClient(app)` used without `with`
    (as this repo's `client` fixture does) never triggers ASGI lifespan,
    so the real thread never runs under pytest. One bad row (e.g. a
    malformed `draft_json`) is caught per-row so it can never take down
    the whole poller.
    """
    now_iso = (now or datetime.now()).replace(microsecond=0).isoformat()

    conn = get_connection()
    rows = conn.execute(
        "SELECT id, draft_json FROM scheduled WHERE sent = 0 AND send_at <= ?",
        (now_iso,),
    ).fetchall()

    results = []
    for row_id, draft_json in rows:
        try:
            draft = Draft.model_validate_json(draft_json)
            result = send_email(draft)
        except Exception as exc:  # noqa: BLE001 - one bad row must never kill the poller
            result = MailResult(success=False, message=str(exc))
        conn.execute("UPDATE scheduled SET sent = 1 WHERE id = ?", (row_id,))
        results.append(result)

    conn.commit()
    return results
