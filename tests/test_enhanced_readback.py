"""F53 ENHANCED_READBACK end-to-end (§11.3/§11.4) — route-level proof that
the toggle changes delivery, never content, for the common (nothing
actually uncertain) case, plus the new F52 spell commands and
is_known_contact.
"""

from backend.config import get_settings
from backend.data.contacts import is_known_contact


def _run_scripted_conversation(client, session_id: str) -> list[dict]:
    """The same two-turn shape test_turn_flow.py's
    test_full_conversation_compose_readback_send uses, stopping before
    'send' since that response isn't a readback.
    """
    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "make it shorter"})
    return [r1.json(), r2.json()]


def test_enhanced_readback_off_has_no_speech_segments(client):
    assert get_settings().enhanced_readback is False  # the test-suite default
    bodies = _run_scripted_conversation(client, "enhanced-off")
    for body in bodies:
        assert body.get("speech_segments") is None


def test_enhanced_readback_on_matches_off_when_nothing_is_uncertain(client, monkeypatch):
    # John Smith is a seeded, known contact and FAKE_AI=1 sends no
    # last_interim_transcript, so nothing here is ever flagged uncertain —
    # the toggle must not change a single word of what's said.
    off_bodies = _run_scripted_conversation(client, "enhanced-compare-off")

    monkeypatch.setenv("ENHANCED_READBACK", "1")
    get_settings.cache_clear()
    try:
        on_bodies = _run_scripted_conversation(client, "enhanced-compare-on")
    finally:
        monkeypatch.delenv("ENHANCED_READBACK", raising=False)
        get_settings.cache_clear()

    for off_body, on_body in zip(off_bodies, on_bodies):
        assert on_body["speech"] == off_body["speech"]
        assert on_body["speech_segments"] is not None
        assert off_body["speech_segments"] is None


def test_enhanced_readback_on_auto_spells_unfamiliar_recipient(client, monkeypatch):
    monkeypatch.setenv("ENHANCED_READBACK", "1")
    get_settings.cache_clear()
    try:
        session_id = "enhanced-unfamiliar"
        client.post(
            "/api/turn", json={"session_id": session_id, "transcript": "tell Zyxlor I will be late"}
        )
        # No seed contact matches "Zyxlor" -> awaiting_address -> any spoken
        # answer resolves it via the permissive stub, which never produces a
        # real contacts-table row (is_known_contact() will be False).
        resp = client.post(
            "/api/turn", json={"session_id": session_id, "transcript": "zyxlor at example dot com"}
        )
        body = resp.json()
        assert body["speech_segments"] is not None
        # The automatic spell-out segment is the one with rate="slow" and
        # cue=False (spelling != uncertainty-marking, see the Phase 11 plan).
        slow_segments = [s for s in body["speech_segments"] if s["rate"] == "slow" and not s["cue"]]
        assert len(slow_segments) == 1
        assert " for " in slow_segments[0]["text"]
    finally:
        monkeypatch.delenv("ENHANCED_READBACK", raising=False)
        get_settings.cache_clear()


# ---------------------------------------------------------------------------
# F52 — is_known_contact() and the spell commands, route-level
# ---------------------------------------------------------------------------


def test_is_known_contact_true_for_seeded_contact():
    assert is_known_contact("john.smith@example.com") is True


def test_is_known_contact_false_for_unknown_address():
    assert is_known_contact("nobody@nowhere.example.com") is False


def test_is_known_contact_false_for_empty_string():
    assert is_known_contact("") is False


def test_spell_the_recipient(client):
    session_id = "spell-recipient"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "spell the recipient"})
    body = resp.json()
    assert "J for Juliet" in body["speech"]


def test_spell_the_subject(client):
    session_id = "spell-subject"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "spell the subject"})
    body = resp.json()
    assert "for" in body["speech"].lower()


def test_spell_that_defaults_to_recipient_right_after_readback(client):
    session_id = "spell-that-default"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "spell that"})
    body = resp.json()
    assert "J for Juliet" in body["speech"]


def test_spell_that_follows_read_subject(client):
    session_id = "spell-that-subject"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read the subject"})

    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "spell that"})
    body = resp.json()
    # Under FAKE_AI=1, "tell John Smith I will be late" -> subject "I Will
    # Be Late". "spell that" must have tracked the switch to the subject
    # (via read_the_subject), not stayed on the recipient ("John Smith").
    assert body["speech"].startswith("I for India")


def test_spell_refused_without_a_draft(client):
    resp = client.post("/api/turn", json={"session_id": "spell-no-draft", "transcript": "spell that"})
    body = resp.json()
    assert body["speech"] == "There's no message to read yet."
