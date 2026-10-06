"""Offline tests for backend/ai/provider.py — no real Ollama connection.

provider.generate() has no fake_ai branch of its own (the fake/real switch
lives one layer up, in compose/edit/mode_detect), so these tests call it
directly and monkeypatch the `ollama.Client` class it constructs — FAKE_AI
stays 1 throughout, as conftest.py mandates, with zero interaction between
the two, and no network call happens anywhere.
"""

import json

import pytest
from pydantic import BaseModel

from backend.ai import provider
from backend.data.store import get_connection
from backend.errors import SpokenError
from backend.events import get_current_session, set_current_session


class _Field(BaseModel):
    value: str


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _QueuedClient:
    """Stand-in for ollama.Client — returns queued responses (or raises
    queued exceptions) in order, one per .chat() call, regardless of how
    many times Client(...) itself is constructed.
    """

    _queue: list = []

    def __init__(self, *args, **kwargs):
        pass

    def chat(self, **kwargs):
        item = _QueuedClient._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


def _install_queue(monkeypatch, items):
    _QueuedClient._queue = list(items)
    monkeypatch.setattr(provider, "Client", _QueuedClient)


def test_generate_succeeds_on_first_valid_response(monkeypatch):
    _install_queue(monkeypatch, ['{"value": "hello"}'])
    result = provider.generate("system", "user", _Field)
    assert result.value == "hello"


def test_generate_retries_once_then_succeeds(monkeypatch):
    _install_queue(monkeypatch, ["not valid json at all", '{"value": "recovered"}'])
    result = provider.generate("system", "user", _Field)
    assert result.value == "recovered"


def test_generate_gives_up_after_second_failure(monkeypatch):
    _install_queue(monkeypatch, ["still not json", "still not json"])
    with pytest.raises(SpokenError) as exc_info:
        provider.generate("system", "user", _Field)
    assert exc_info.value.message == "I couldn't write that properly, so nothing was sent. Could you say it again?"


def test_generate_speaks_ollama_not_running(monkeypatch):
    _install_queue(monkeypatch, [ConnectionError("Failed to connect to Ollama...")])
    with pytest.raises(SpokenError) as exc_info:
        provider.generate("system", "user", _Field)
    assert "Ollama isn't running" in exc_info.value.message


def test_generate_speaks_generic_ollama_error(monkeypatch):
    from ollama import ResponseError

    _install_queue(monkeypatch, [ResponseError("boom", 500)])
    with pytest.raises(SpokenError) as exc_info:
        provider.generate("system", "user", _Field)
    assert exc_info.value.message == "The writing assistant ran into a problem, so nothing was sent. Say it again in a moment."


def _events_for(session_id: str) -> list[tuple]:
    return get_connection().execute(
        "SELECT event, ms, detail FROM events WHERE session_id = ? ORDER BY id", (session_id,)
    ).fetchall()


def test_generate_logs_llm_call_on_success(monkeypatch):
    _install_queue(monkeypatch, ['{"value": "hello there"}'])
    set_current_session("provider-success")
    try:
        provider.generate("system", "user", _Field)
    finally:
        set_current_session(None)

    rows = _events_for("provider-success")
    assert len(rows) == 1
    event, ms, detail_raw = rows[0]
    assert event == "llm_call"
    assert ms is not None
    detail = json.loads(detail_raw)
    assert detail["fn"] == "_Field"
    assert detail["retried"] is False
    assert detail["output_words"] > 0


def test_generate_logs_retried_true_on_a_retry(monkeypatch):
    _install_queue(monkeypatch, ["not valid json at all", '{"value": "recovered"}'])
    set_current_session("provider-retried")
    try:
        provider.generate("system", "user", _Field)
    finally:
        set_current_session(None)

    rows = _events_for("provider-retried")
    assert len(rows) == 1
    detail = json.loads(rows[0][2])
    assert detail["retried"] is True


def test_generate_logs_nothing_without_a_current_session(monkeypatch):
    # Simulates /api/draft/compose calling compose_email() -> generate()
    # directly, with no voice.py turn (and thus no session) involved.
    set_current_session(None)
    assert get_current_session() is None
    before = get_connection().execute("SELECT COUNT(*) FROM events").fetchone()[0]
    _install_queue(monkeypatch, ['{"value": "hello"}'])
    provider.generate("system", "user", _Field)
    after = get_connection().execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert after == before
