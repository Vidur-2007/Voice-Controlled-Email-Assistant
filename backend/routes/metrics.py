"""GET /api/metrics/* (F54, PHASE_10_PLUS_SPEC.md §10.2) — derived purely
from the `events` table. Read-only, never touched by the conversational
flow itself; this is what you analyse after a study session (§33's
evaluation protocol).
"""

import csv
import io
import json
from collections import defaultdict
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import Response

from backend.data.store import get_connection

router = APIRouter()

# A send is "abandoned" when CANCEL/RESTART fires while a draft was
# genuinely in progress (phase != idle at the moment the command matched —
# command_matched's own phase column already captures the PRE-dispatch
# phase, so this needs no new event type).
_ABANDON_INTENTS = {"CANCEL", "RESTART"}
_LATE_EDIT_KINDS = {"tone", "length", "free_form"}


def _rows():
    conn = get_connection()
    return conn.execute(
        "SELECT id, session_id, ts, event, phase, ms, detail FROM events ORDER BY id"
    ).fetchall()


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def _avg(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


@router.get("/metrics/summary")
def metrics_summary():
    per_session = defaultdict(
        lambda: {"turns": 0, "repair_turns": 0, "sent": False, "first_ts": None, "send_ts": None}
    )
    latencies: dict[str, list[float]] = defaultdict(list)
    edits_after_readback = 0
    sends_abandoned = 0
    readbacks_by_condition = {"plain": 0, "enhanced": 0}

    for _id, session_id, ts, event, phase, ms, detail_raw in _rows():
        detail = json.loads(detail_raw) if detail_raw else {}
        s = per_session[session_id]
        if s["first_ts"] is None:
            s["first_ts"] = ts

        if event == "turn_start":
            s["turns"] += 1
        elif event == "repair_turn":
            s["repair_turns"] += 1
        elif event == "edit_requested" and detail.get("kind") in _LATE_EDIT_KINDS:
            edits_after_readback += 1
        elif event == "llm_call" and ms is not None:
            latencies[detail.get("fn", "unknown")].append(ms)
        elif event == "send_result" and detail.get("success"):
            s["sent"] = True
            s["send_ts"] = ts
        elif event == "command_matched" and detail.get("intent") in _ABANDON_INTENTS and phase and phase != "idle":
            sends_abandoned += 1
        elif event == "readback_start":
            key = "enhanced" if detail.get("enhanced") else "plain"
            readbacks_by_condition[key] += 1

    sessions_summary = []
    turns_per_send, repair_per_send, wall_clock = [], [], []
    for session_id, s in per_session.items():
        sessions_summary.append(
            {"session_id": session_id, "turns": s["turns"], "repair_turns": s["repair_turns"], "sent": s["sent"]}
        )
        if s["sent"]:
            turns_per_send.append(s["turns"])
            repair_per_send.append(s["repair_turns"])
            if s["first_ts"] and s["send_ts"]:
                try:
                    start = datetime.fromisoformat(s["first_ts"])
                    end = datetime.fromisoformat(s["send_ts"])
                    wall_clock.append((end - start).total_seconds())
                except ValueError:
                    pass

    model_latency = {
        fn: {"median_ms": _percentile(values, 0.5), "p95_ms": _percentile(values, 0.95)}
        for fn, values in latencies.items()
    }

    return {
        "sessions": sessions_summary,
        "aggregate": {
            "turns_per_send": _avg(turns_per_send),
            "repair_turns_per_send": _avg(repair_per_send),
            "wall_clock_seconds_avg": _avg(wall_clock),
            "model_latency_ms": model_latency,
            "edits_after_readback": edits_after_readback,
            "sends_abandoned": sends_abandoned,
            "readbacks_by_condition": readbacks_by_condition,
        },
    }


@router.get("/metrics/export.csv")
def metrics_export_csv():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "session_id", "ts", "event", "phase", "ms", "detail"])
    for row in _rows():
        writer.writerow(row)
    return Response(content=buf.getvalue(), media_type="text/csv")
