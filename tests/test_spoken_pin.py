"""F51 (Phase 14, optional) — spoken PIN before sending sensitive content
(PHASE_10_PLUS_SPEC.md §14). Off entirely unless SEND_PIN is set.
"""

from backend.config import get_settings
from backend.sensitive_content import contains_sensitive_markers, parse_spoken_pin


# ---------------------------------------------------------------------------
# contains_sensitive_markers / parse_spoken_pin — pure functions
# ---------------------------------------------------------------------------


def test_contains_sensitive_markers_password_keyword():
    assert contains_sensitive_markers("My Password is secret") is True


def test_contains_sensitive_markers_otp_keyword_case_insensitive():
    assert contains_sensitive_markers("here is your OTP") is True


def test_contains_sensitive_markers_digit_run():
    assert contains_sensitive_markers("the account number is 1234567") is True


def test_contains_sensitive_markers_card_like_formatted_run():
    assert contains_sensitive_markers("card: 4111 1111 1111 1111") is True


def test_contains_sensitive_markers_ordinary_text_is_false():
    assert contains_sensitive_markers("I will be at the office at 5") is False


def test_parse_spoken_pin_literal_digits():
    assert parse_spoken_pin("1234") == "1234"


def test_parse_spoken_pin_spoken_words():
    assert parse_spoken_pin("one two three four") == "1234"


def test_parse_spoken_pin_mixed():
    assert parse_spoken_pin("one 2 three 4") == "1234"


def test_parse_spoken_pin_oh_as_zero():
    assert parse_spoken_pin("one oh oh one") == "1001"


def test_parse_spoken_pin_wrong_length_is_none():
    assert parse_spoken_pin("12345") is None
    assert parse_spoken_pin("123") is None


def test_parse_spoken_pin_no_digits_is_none():
    assert parse_spoken_pin("cancel that") is None


# ---------------------------------------------------------------------------
# Route-level — off by default, since SEND_PIN is unset in the test suite
# ---------------------------------------------------------------------------


def test_sensitive_send_goes_through_unprompted_when_pin_disabled(client):
    assert get_settings().send_pin == ""  # the test-suite default
    session_id = "pin-disabled"
    client.post(
        "/api/turn",
        json={"session_id": session_id, "transcript": "tell John Smith my password is 1234 5678"},
    )
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
    body = resp.json()
    assert body["ok"] is True
    assert "Sent to John Smith" in body["speech"]


def test_non_sensitive_send_never_prompts_even_when_pin_enabled(client, monkeypatch):
    monkeypatch.setenv("SEND_PIN", "1234")
    get_settings.cache_clear()
    try:
        session_id = "pin-enabled-not-sensitive"
        client.post(
            "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
        )
        resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
        body = resp.json()
        assert body["ok"] is True
        assert "Sent to John Smith" in body["speech"]
    finally:
        monkeypatch.delenv("SEND_PIN", raising=False)
        get_settings.cache_clear()


def test_sensitive_send_prompts_for_pin_and_correct_pin_sends(client, monkeypatch):
    monkeypatch.setenv("SEND_PIN", "1234")
    get_settings.cache_clear()
    try:
        session_id = "pin-correct"
        client.post(
            "/api/turn",
            json={"session_id": session_id, "transcript": "tell John Smith my password is 1234 5678"},
        )
        prompt = client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
        prompt_body = prompt.json()
        assert prompt_body["phase"] == "awaiting_pin"
        assert "4-digit PIN" in prompt_body["speech"]

        resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "one two three four"})
        body = resp.json()
        assert body["ok"] is True
        assert "Sent to John Smith" in body["speech"]
    finally:
        monkeypatch.delenv("SEND_PIN", raising=False)
        get_settings.cache_clear()


def test_wrong_pin_three_times_refuses_and_keeps_draft(client, monkeypatch):
    monkeypatch.setenv("SEND_PIN", "1234")
    get_settings.cache_clear()
    try:
        session_id = "pin-wrong"
        client.post(
            "/api/turn",
            json={"session_id": session_id, "transcript": "tell John Smith my password is 1234 5678"},
        )
        client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})

        r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "nine nine nine nine"})
        assert r1.json()["ok"] is False
        assert "2 more tries" in r1.json()["speech"]

        r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "nine nine nine nine"})
        assert "1 more try" in r2.json()["speech"]

        r3 = client.post("/api/turn", json={"session_id": session_id, "transcript": "nine nine nine nine"})
        body = r3.json()
        assert body["ok"] is False
        assert body["speech"] == "That PIN didn't match three times, so I haven't sent this. Your draft is safe."
        assert body["phase"] == "awaiting_confirm"
        assert body["draft"]["recipient_name"] == "John Smith"
    finally:
        monkeypatch.delenv("SEND_PIN", raising=False)
        get_settings.cache_clear()


def test_unparseable_pin_reasks_without_consuming_an_attempt(client, monkeypatch):
    monkeypatch.setenv("SEND_PIN", "1234")
    get_settings.cache_clear()
    try:
        session_id = "pin-garbled"
        client.post(
            "/api/turn",
            json={"session_id": session_id, "transcript": "tell John Smith my password is 1234 5678"},
        )
        client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})

        r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "sorry what"})
        assert r1.json()["speech"] == (
            "I need a 4-digit PIN to send this. Please say the 4 digits now, or say cancel."
        )

        # Still on the first attempt — a valid-but-wrong PIN now should say
        # "2 more tries", not "1 more try", proving the garbled answer
        # above never counted as a failed attempt.
        r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "nine nine nine nine"})
        assert "2 more tries" in r2.json()["speech"]
    finally:
        monkeypatch.delenv("SEND_PIN", raising=False)
        get_settings.cache_clear()


def test_cancel_during_pin_entry_discards_everything(client, monkeypatch):
    monkeypatch.setenv("SEND_PIN", "1234")
    get_settings.cache_clear()
    try:
        session_id = "pin-cancel"
        client.post(
            "/api/turn",
            json={"session_id": session_id, "transcript": "tell John Smith my password is 1234 5678"},
        )
        client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
        resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "cancel"})
        body = resp.json()
        assert body["speech"] == "Cancelled. Nothing was sent."
        assert body["phase"] == "idle"
    finally:
        monkeypatch.delenv("SEND_PIN", raising=False)
        get_settings.cache_clear()


def test_send_while_awaiting_pin_gets_a_specific_message(client, monkeypatch):
    monkeypatch.setenv("SEND_PIN", "1234")
    get_settings.cache_clear()
    try:
        session_id = "pin-impatient"
        client.post(
            "/api/turn",
            json={"session_id": session_id, "transcript": "tell John Smith my password is 1234 5678"},
        )
        client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
        resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
        assert resp.json()["speech"] == "I'm still waiting for your 4-digit PIN. Please say it now, or say cancel."
    finally:
        monkeypatch.delenv("SEND_PIN", raising=False)
        get_settings.cache_clear()


def test_search_blocked_while_awaiting_pin(client, monkeypatch):
    monkeypatch.setenv("SEND_PIN", "1234")
    get_settings.cache_clear()
    try:
        session_id = "pin-blocks-inbox"
        client.post(
            "/api/turn",
            json={"session_id": session_id, "transcript": "tell John Smith my password is 1234 5678"},
        )
        client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
        resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
        body = resp.json()
        assert body["phase"] == "awaiting_pin"
        assert "middle of a message" in body["speech"]
    finally:
        monkeypatch.delenv("SEND_PIN", raising=False)
        get_settings.cache_clear()
