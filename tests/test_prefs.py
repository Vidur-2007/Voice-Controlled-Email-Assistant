"""Offline tests for backend/data/prefs.py (F42/F44/F45) and the new
/api/prefs route (F45). No network calls.
"""

from backend.data import prefs

# ---------------------------------------------------------------------------
# get_pref / set_pref (F45)
# ---------------------------------------------------------------------------


def test_get_pref_returns_default_when_unset():
    assert prefs.get_pref("nope", default="fallback") == "fallback"
    assert prefs.get_pref("nope") is None


def test_set_pref_then_get_pref_round_trips():
    prefs.set_pref("speech_rate", "1.25")
    assert prefs.get_pref("speech_rate") == "1.25"


def test_set_pref_overwrites_existing_value():
    prefs.set_pref("speech_rate", "1.0")
    prefs.set_pref("speech_rate", "1.4")
    assert prefs.get_pref("speech_rate") == "1.4"


# ---------------------------------------------------------------------------
# get_tone_for_recipient / set_tone_for_recipient (F42)
# ---------------------------------------------------------------------------


def test_tone_for_recipient_unset_returns_none():
    assert prefs.get_tone_for_recipient("nobody@example.com") is None


def test_tone_for_recipient_round_trips():
    prefs.set_tone_for_recipient("john.smith@example.com", "formal")
    assert prefs.get_tone_for_recipient("john.smith@example.com") == "formal"


def test_tone_for_recipient_is_case_insensitive():
    prefs.set_tone_for_recipient("John.Smith@Example.com", "friendly")
    assert prefs.get_tone_for_recipient("john.smith@example.com") == "friendly"


def test_tone_for_recipient_overwrites_on_resend():
    prefs.set_tone_for_recipient("john.smith@example.com", "formal")
    prefs.set_tone_for_recipient("john.smith@example.com", "firm")
    assert prefs.get_tone_for_recipient("john.smith@example.com") == "firm"


def test_set_tone_for_recipient_ignores_empty_email():
    prefs.set_tone_for_recipient("", "formal")  # must not raise
    assert prefs.get_tone_for_recipient("") is None


# ---------------------------------------------------------------------------
# record_phrase / top_phrases (F44 — bookkeeping only)
# ---------------------------------------------------------------------------


def test_record_phrase_inserts_new_phrase():
    prefs.record_phrase("Best regards,")
    assert prefs.top_phrases() == [("Best regards,", 1)]


def test_record_phrase_increments_use_count_on_repeat():
    prefs.record_phrase("Thanks,")
    prefs.record_phrase("Thanks,")
    prefs.record_phrase("Thanks,")
    assert prefs.top_phrases() == [("Thanks,", 3)]


def test_record_phrase_skips_empty_text():
    prefs.record_phrase("")
    prefs.record_phrase("   ")
    assert prefs.top_phrases() == []


def test_record_phrase_skips_text_over_60_chars():
    long_text = "x" * 61
    prefs.record_phrase(long_text)
    assert prefs.top_phrases() == []


def test_record_phrase_accepts_text_at_60_chars():
    text = "x" * 60
    prefs.record_phrase(text)
    assert prefs.top_phrases() == [(text, 1)]


def test_top_phrases_orders_by_use_count_desc():
    prefs.record_phrase("Thanks,")
    prefs.record_phrase("Best,")
    prefs.record_phrase("Best,")
    prefs.record_phrase("Best,")
    assert prefs.top_phrases() == [("Best,", 3), ("Thanks,", 1)]


def test_top_phrases_respects_limit():
    prefs.record_phrase("A")
    prefs.record_phrase("B")
    prefs.record_phrase("C")
    assert len(prefs.top_phrases(limit=2)) == 2


# ---------------------------------------------------------------------------
# GET/POST /api/prefs route
# ---------------------------------------------------------------------------


def test_get_prefs_default(client):
    resp = client.get("/api/prefs")
    assert resp.json() == {"speech_rate": 1.0}


def test_post_prefs_round_trips(client):
    resp = client.post("/api/prefs", json={"speech_rate": 1.25})
    assert resp.json() == {"speech_rate": 1.25}

    resp2 = client.get("/api/prefs")
    assert resp2.json() == {"speech_rate": 1.25}


def test_post_prefs_clamps_too_high(client):
    resp = client.post("/api/prefs", json={"speech_rate": 5.0})
    assert resp.json() == {"speech_rate": 1.5}


def test_post_prefs_clamps_too_low(client):
    resp = client.post("/api/prefs", json={"speech_rate": 0.1})
    assert resp.json() == {"speech_rate": 0.75}
