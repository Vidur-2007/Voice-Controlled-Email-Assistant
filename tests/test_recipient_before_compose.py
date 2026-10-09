"""F59 (Phase 12) — recipient-before-compose reorder (PHASE_10_PLUS_SPEC.md
§12). Confirms the reordering itself: no DraftFields (compose) llm_call
happens before an ambiguous name is disambiguated, a previously-learned
tone reaches the compose prompt (not just the Draft.tone field), and a
transcript with no identifiable recipient still composes exactly as
before.
"""

import json

from backend.ai import provider
from backend.config import get_settings
from backend.ai.compose import extract_recipient_hint
from backend.data.store import get_connection
from backend.data.prefs import set_tone_for_recipient


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _QueuedClient:
    """Same stand-in tests/test_provider.py uses — returns queued .chat()
    responses in order, regardless of how many times Client(...) itself
    is constructed.
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


def _llm_call_fns(session_id: str) -> list[str]:
    rows = get_connection().execute(
        "SELECT detail FROM events WHERE session_id = ? AND event = 'llm_call'", (session_id,)
    ).fetchall()
    return [json.loads(r[0])["fn"] for r in rows]


# ---------------------------------------------------------------------------
# extract_recipient_hint() — no model call, pure function
# ---------------------------------------------------------------------------


def test_extract_recipient_hint_fires_on_tell():
    assert extract_recipient_hint("tell John Smith I will be late") == "John Smith"


def test_extract_recipient_hint_fires_on_email():
    assert extract_recipient_hint("email Sarah about the budget") == "Sarah"


def test_extract_recipient_hint_fires_on_write_to():
    assert extract_recipient_hint("write to John that the report is ready") == "John"


def test_extract_recipient_hint_handles_possessive_alias():
    assert extract_recipient_hint("tell my manager I will be late") == "my manager"


def test_extract_recipient_hint_handles_group():
    assert extract_recipient_hint("email the whole team about the launch") == "the whole team"


def test_extract_recipient_hint_empty_for_no_trigger_word():
    assert extract_recipient_hint("I need help with the report") == ""


def test_extract_recipient_hint_empty_for_empty_transcript():
    assert extract_recipient_hint("") == ""


# ---------------------------------------------------------------------------
# The reorder itself, under FAKE_AI=0 so a real compose call would be
# visible (and would crash loudly — see the test below) if it happened.
# ---------------------------------------------------------------------------


def test_ambiguous_name_asks_before_any_compose_llm_call(client, monkeypatch):
    monkeypatch.setenv("FAKE_AI", "0")
    get_settings.cache_clear()
    try:
        # Exactly one queued response: the ContactChoice resolution
        # contacts_nlp.py::resolve() legitimately makes while trying to
        # disambiguate "John" among the two seeded candidates — a
        # pre-existing, unrelated model call this phase doesn't touch.
        # An empty choice (declines to pick) falls back to the
        # deterministic disambiguation question, same as FAKE_AI=1 does.
        _install_queue(monkeypatch, ['{"email": "", "question": ""}'])
        resp = client.post(
            "/api/turn", json={"session_id": "f59-ambiguous", "transcript": "email John about the budget"}
        )
        body = resp.json()
        assert body["ok"] is True
        assert body["phase"] == "clarifying"

        # The real proof: no DraftFields (compose) llm_call ever fired —
        # only the ContactChoice resolution call above. If compose_email()
        # had been called before clarifying, _QueuedClient's queue would
        # already be empty and raise IndexError, which would have
        # surfaced as ok=False/phase="idle" above instead.
        assert _llm_call_fns("f59-ambiguous") == ["ContactChoice"]
    finally:
        monkeypatch.delenv("FAKE_AI", raising=False)
        get_settings.cache_clear()


def test_resolved_recipient_tone_reaches_the_compose_prompt(client, monkeypatch):
    set_tone_for_recipient("john.smith@example.com", "formal")
    monkeypatch.setenv("FAKE_AI", "0")
    get_settings.cache_clear()
    try:
        captured_user_messages = []

        class _CapturingClient(_QueuedClient):
            def chat(self, **kwargs):
                captured_user_messages.append(kwargs["messages"][-1]["content"])
                return super().chat(**kwargs)

        _QueuedClient._queue = [
            '{"recipient_hint": "John Smith", "subject": "Update", "body": "The project is delayed.", "tone": "neutral"}'
        ]
        monkeypatch.setattr(provider, "Client", _CapturingClient)

        resp = client.post(
            "/api/turn",
            json={"session_id": "f59-tone", "transcript": "tell John Smith the project is delayed"},
        )
        body = resp.json()
        assert body["ok"] is True
        assert body["phase"] == "awaiting_confirm"
        assert body["draft"]["tone"] == "formal"
        # Not just the field — the prompt itself carried the tone, proving
        # it reached the model before the body was written, not patched
        # onto the Draft afterward (the gap F59 exists to close).
        assert any("formal" in msg for msg in captured_user_messages)
    finally:
        monkeypatch.delenv("FAKE_AI", raising=False)
        get_settings.cache_clear()


def test_no_identifiable_recipient_still_composes_as_before(client):
    resp = client.post(
        "/api/turn", json={"session_id": "f59-no-hint", "transcript": "I need help with the report"}
    )
    body = resp.json()
    assert body["phase"] == "awaiting_address"
    assert body["speech"] == "Who should I send this to?"


# ---------------------------------------------------------------------------
# The clarifying phase's new (pre-compose) shape, under FAKE_AI=1
# ---------------------------------------------------------------------------


def test_clarifying_resolution_composes_after_answering(client):
    session_id = "f59-clarify-then-compose"
    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "email John about the budget"}
    )
    assert r1.json()["phase"] == "clarifying"

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "Smith"})
    body = r2.json()
    assert body["phase"] == "awaiting_confirm"
    assert body["draft"]["recipient_name"] == "John Smith"
    assert body["draft"]["body"]  # a draft now genuinely exists


def test_clarifying_resolution_applies_learned_tone(client):
    set_tone_for_recipient("john.smith@example.com", "formal")
    session_id = "f59-clarify-tone"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "email John about the budget"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "Smith"})
    body = resp.json()
    assert body["draft"]["tone"] == "formal"


def test_clarifying_reask_on_mismatch_still_works_pre_compose(client):
    session_id = "f59-clarify-mismatch"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "email John about the budget"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "banana"})
    body = resp.json()
    assert body["phase"] == "clarifying"
    assert "Sorry, I didn't catch that." in body["speech"]
