"""F54 instrumentation (PHASE_10_PLUS_SPEC.md §10.2) — the one place events
get written, the one place LOG_CONTENT is checked, and the one place a
"repair turn" is named.

Purely additive to Phases 0-9: nothing here is spoken or shown to the
user, so a bug in this module must never surface as a broken turn — every
call site is a plain fire-and-forget write.
"""

import json
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

from backend.config import get_settings
from backend.data.store import get_connection

# Lets provider.py's ONE llm-call site (ai/provider.py::_generate_ollama)
# log against the right session without threading a session_id parameter
# through every compose.py/edit.py/mode_detect.py/summarize.py caller.
# Safe across concurrent requests: each request gets its own copy of the
# ASGI task's context (which never had this set) before FastAPI hands the
# sync handler to a worker thread, so one request's .set() never leaks
# into another's.
_current_session: ContextVar[Optional[str]] = ContextVar("_current_session", default=None)


def set_current_session(session_id: Optional[str]) -> None:
    _current_session.set(session_id)


def get_current_session() -> Optional[str]:
    return _current_session.get()


def log_event(
    session_id: str,
    event: str,
    *,
    phase: Optional[str] = None,
    ms: Optional[int] = None,
    detail: Optional[dict[str, Any]] = None,
    content: Optional[dict[str, Any]] = None,
) -> None:
    """The ONLY writer of the events table, and the ONLY place LOG_CONTENT
    is checked. A call site passes `content` freely, without checking
    anything itself — it is merged into `detail` only when
    settings.log_content is True (default False; see the privacy rule in
    PHASE_10_PLUS_SPEC.md §10.2). This is the single place to audit for
    that guarantee, not N call sites to each get right.
    """
    merged = dict(detail or {})
    if content and get_settings().log_content:
        merged.update(content)
    conn = get_connection()
    conn.execute(
        "INSERT INTO events (session_id, ts, event, phase, ms, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, datetime.now(timezone.utc).isoformat(), event, phase, ms, json.dumps(merged)),
    )
    conn.commit()


def classify_repair_turn(
    *,
    self_corrected: bool = False,
    undo: bool = False,
    redo: bool = False,
    start_over: bool = False,
    reclarify: bool = False,
    late_edit: bool = False,
) -> Optional[str]:
    """The ONLY place a "repair turn" is named (§10.2: "classify these in
    one place so the definition stays consistent"). Every call site flips
    exactly one boolean signal it already has on hand; the mapping from
    signal to reason, and the priority if more than one were ever true at
    once, lives here and nowhere else. `redo` is tracked as a deliberate,
    symmetric extension beyond the addendum's literal reason list.
    """
    if self_corrected:
        return "self_correction"
    if undo:
        return "undo"
    if redo:
        return "redo"
    if start_over:
        return "start_over"
    if reclarify:
        return "reclarify"
    if late_edit:
        return "late_edit"
    return None


# Short, content-free category slugs for `error_spoken`'s `detail.category`
# — never the spoken sentence itself. Checked in order against the spoken
# message's text, mirroring backend/errors.py's own pattern-matching style.
_ERROR_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    ("credentials file is missing", "missing_credentials"),
    ("access to your email has expired", "auth_expired"),
    ("refused the request", "auth_refused"),
    ("busy right now", "provider_busy"),
    ("doesn't look right", "invalid_recipient"),
    ("writing assistant isn't set up", "llm_not_configured"),
    ("couldn't reach the internet", "network_down"),
    ("couldn't write that properly", "llm_validation_failed"),
    ("taking too long to write", "llm_timeout"),
    ("ran into a problem", "llm_error"),
    ("didn't catch that", "empty_transcript"),
    ("haven't read the message back", "send_too_early"),
]


def categorize_error(speech: str) -> str:
    """A coarse, content-free category for a spoken failure message —
    never the message itself, so `error_spoken` can never carry a body,
    subject, or address even if a future failure message happened to
    quote one.
    """
    low = speech.lower()
    for needle, category in _ERROR_CATEGORY_KEYWORDS:
        if needle in low:
            return category
    return "other"
