"""Regression tests for four live bug reports:
1. No way to change the recipient once a draft exists.
2. A spoken name ASR split into two words ("vidur bandaru") got a "."
   inserted between them in the resulting fake address.
3. "Dictate this, ..." (comma at the natural speech pause) leaked the
   literal words "dictate this" into the composed content instead of
   being stripped as a mode override.
4. "read my unread mails" (plural) fell through to AI composition
   instead of matching READ_INBOX.
"""

from backend.ai.mode_detect import check_override
from backend.commands import match_change_recipient, match_reply_all_trigger, match_reply_trigger, parse_command
from backend.routes.voice import _parse_spoken_email, _resolve_recipient_stub


# ---------------------------------------------------------------------------
# Bug 2 — spoken email address parsing
# ---------------------------------------------------------------------------


def test_parse_spoken_email_two_words_no_dot_inserted():
    name, email = _parse_spoken_email("vidur bandaru at gmail dot com")
    assert email == "vidurbandaru@gmail.com"
    assert name == "Vidur Bandaru"


def test_parse_spoken_email_with_explicit_dot_in_local_part():
    name, email = _parse_spoken_email("vidur dot bandaru at gmail dot com")
    assert email == "vidur.bandaru@gmail.com"
    assert name == "Vidur Bandaru"  # the word "dot" itself never shows up in the display name


def test_parse_spoken_email_handles_chrome_smart_formatted_at_sign():
    # Observed live: Chrome's own speech recognition sometimes converts
    # "at"/"dot" into literal "@"/"." mid-utterance on its own.
    name, email = _parse_spoken_email("VVS mini project 1.0@gmail.com")
    assert email == "vvsminiproject1.0@gmail.com"
    assert name == "Vvs Mini Project 1.0"


def test_parse_spoken_email_none_without_at():
    assert _parse_spoken_email("vidur bandaru") is None


def test_parse_spoken_email_none_for_malformed_domain():
    assert _parse_spoken_email("vidur at gmail") is None  # no "dot" at all


def test_resolve_recipient_stub_uses_real_address_when_spoken():
    name, email = _resolve_recipient_stub("vidur bandaru at gmail dot com")
    assert email == "vidurbandaru@gmail.com"
    assert name == "Vidur Bandaru"


def test_resolve_recipient_stub_falls_back_to_placeholder_for_a_bare_name():
    name, email = _resolve_recipient_stub("Zyxlor")
    assert email == "zyxlor@example.com"
    assert name == "Zyxlor"


def test_awaiting_address_route_level_produces_real_address(client):
    session_id = "bug2-route"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell Vidur I will be late"})
    resp = client.post(
        "/api/turn",
        json={"session_id": session_id, "transcript": "vidur bandaru at gmail dot com"},
    )
    body = resp.json()
    assert body["draft"]["recipient"] == "vidurbandaru@gmail.com"
    assert body["phase"] == "awaiting_confirm"


# ---------------------------------------------------------------------------
# Bug 1 — "change recipient" was promised by error messages but never wired
# ---------------------------------------------------------------------------


def test_change_recipient_is_now_a_real_command(client):
    session_id = "bug1-change"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "change recipient"})
    body = resp.json()
    assert body["phase"] == "awaiting_address"
    assert body["speech"] == "Who should I send this to?"


def test_change_recipient_then_new_address_updates_the_draft(client):
    session_id = "bug1-change-full"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "change recipient"})
    resp = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "sarah bandaru at gmail dot com"}
    )
    body = resp.json()
    assert body["draft"]["recipient"] == "sarahbandaru@gmail.com"
    # The body/subject written for John Smith must survive the recipient
    # change unchanged — only the recipient fields should move.
    assert body["draft"]["body"]


def test_change_recipient_to_a_known_contact_resolves_via_real_lookup(client):
    session_id = "bug1-change-known"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "change recipient"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "Sarah Lee"})
    body = resp.json()
    assert body["draft"]["recipient"] == "sarah.lee@example.com"
    assert body["draft"]["recipient_name"] == "Sarah Lee"


def test_change_recipient_refused_without_a_draft(client):
    resp = client.post(
        "/api/turn", json={"session_id": "bug1-no-draft", "transcript": "change recipient"}
    )
    assert "only available" in resp.json()["speech"]


def test_change_recipient_to_x_in_one_utterance(client):
    # The exact shape from the live bug report: the new address said in
    # the same breath as "change the recipient to", not as a separate
    # follow-up turn.
    session_id = "bug1-one-utterance"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "transcript": "change the recipient to vidur bandaru at gmail dot com",
        },
    )
    body = resp.json()
    assert body["draft"]["recipient"] == "vidurbandaru@gmail.com"
    assert body["phase"] == "awaiting_confirm"


def test_change_recipient_to_x_handles_chrome_smart_formatted_address(client):
    session_id = "bug1-smart-format"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "transcript": "change the recipient to VVS mini project 1.0@gmail.com",
        },
    )
    body = resp.json()
    assert body["draft"]["recipient"] == "vvsminiproject1.0@gmail.com"


def test_change_recipient_to_x_refused_without_a_draft(client):
    resp = client.post(
        "/api/turn",
        json={"session_id": "bug1-utterance-no-draft", "transcript": "change the recipient to Sarah Lee"},
    )
    assert "only available" in resp.json()["speech"]


# ---------------------------------------------------------------------------
# Round 2 — "recipient" itself gets mis-heard by ASR (observed live,
# twice: "change receipetant to ..."). An exact-phrase trigger can never
# tolerate this; match_change_recipient() fuzzy-matches the target word
# instead.
# ---------------------------------------------------------------------------


def test_match_change_recipient_tolerates_mis_heard_recipient():
    assert match_change_recipient("change receipetant to bandaru weather@gmail.com") == (
        "bandaru weather@gmail.com"
    )


def test_match_change_recipient_tolerates_other_likely_mishearings():
    for mishearing in ("recipiant", "recipitant", "receiptant", "receipient"):
        assert match_change_recipient(f"change {mishearing} to Sarah Lee") == "Sarah Lee"


def test_match_change_recipient_bare_with_mishearing():
    assert match_change_recipient("change receipetant") == ""


def test_match_change_recipient_does_not_false_positive_on_unrelated_edits():
    assert match_change_recipient("change the tone to formal") is None
    assert match_change_recipient("change the subject to budget update") is None


def test_match_change_recipient_requires_leading_change():
    assert match_change_recipient("the recipient should be Sarah Lee") is None


def test_change_recipient_with_mis_heard_word_route_level(client):
    session_id = "bug1-round2-mishearing"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "transcript": "change receipetant to bandaru weather@gmail.com",
        },
    )
    body = resp.json()
    assert body["draft"]["recipient"] == "bandaruweather@gmail.com"
    assert body["phase"] == "awaiting_confirm"


# ---------------------------------------------------------------------------
# Round 3 — "reply <content>" / "reply all <content>" said as one
# utterance fell through to "That's not available yet" instead of
# actually composing the reply (reported live).
# ---------------------------------------------------------------------------


def test_match_reply_trigger_captures_content():
    assert match_reply_trigger("reply tell them I will be late") == "tell them I will be late"


def test_match_reply_trigger_bare_returns_none():
    # The bare "reply" (no content) stays the existing two-step _PHRASES
    # entry's job, not this trigger's.
    assert match_reply_trigger("reply") is None


def test_match_reply_all_trigger_matches_before_bare_reply_would():
    # match_reply_trigger alone would ALSO match "reply all ..." (it's a
    # valid prefix match too) — disambiguation relies on _handle_turn()
    # checking match_reply_all_trigger first, not on this function
    # rejecting it standalone. The route-level test below is the real
    # guarantee that "reply all ..." ends up as REPLY_ALL, not REPLY.
    assert match_reply_all_trigger("reply all tell everyone I will be late") == "tell everyone I will be late"


def test_reply_with_content_in_one_utterance_route_level(client):
    session_id = "bug-reply-one-utterance"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    resp = client.post(
        "/api/turn",
        json={"session_id": session_id, "transcript": "reply tell them I will be late"},
    )
    body = resp.json()
    assert body["ok"] is True
    assert body["phase"] == "awaiting_confirm"
    assert body["draft"]["body"]


def test_reply_all_with_content_in_one_utterance_route_level(client):
    session_id = "bug-reply-all-one-utterance"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"}
    )
    client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})  # a thread with a CC
    resp = client.post(
        "/api/turn",
        json={"session_id": session_id, "transcript": "reply all tell everyone I will be late"},
    )
    body = resp.json()
    assert body["ok"] is True
    assert body["phase"] == "awaiting_confirm"
    assert body["draft"]["body"]
    # The real proof this dispatched to REPLY_ALL, not plain REPLY: David
    # Chen's seeded message has a CC list, which only reply-all carries over.
    assert body["draft"]["cc"]


def test_reply_with_content_refused_without_inbox_loaded(client):
    resp = client.post(
        "/api/turn",
        json={"session_id": "bug-reply-no-inbox", "transcript": "reply tell them I will be late"},
    )
    assert "haven't opened your inbox" in resp.json()["speech"]


def test_bare_reply_still_works_as_a_two_step_flow(client):
    # Regression guard: the existing two-turn flow (say "reply" alone,
    # then the content next) must still work unchanged.
    session_id = "bug-reply-two-step-regression"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "reply"})
    assert r1.json()["phase"] == "review"
    r2 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell them I will be late"}
    )
    body = r2.json()
    assert body["phase"] == "awaiting_confirm"
    assert body["draft"]["body"]


# ---------------------------------------------------------------------------
# Bug 3 — "dictate this," (trailing comma) must still trigger the override
# ---------------------------------------------------------------------------


def test_check_override_tolerates_trailing_comma():
    assert check_override("Dictate this, I will be late") == ("dictation", "I will be late")


def test_check_override_tolerates_trailing_colon():
    assert check_override("Dictate this: I will be late") == ("dictation", "I will be late")


def test_check_override_still_works_with_plain_space():
    assert check_override("Dictate this I will be late") == ("dictation", "I will be late")


def test_check_override_does_not_false_positive_on_longer_word():
    assert check_override("Dictate thistle report") is None


def test_dictate_this_with_comma_route_level_does_not_leak_into_body(client):
    resp = client.post(
        "/api/turn",
        json={"session_id": "bug3-route", "transcript": "Dictate this, tell Sarah Lee I will be late"},
    )
    body = resp.json()
    # The literal words "dictate this" must not appear in the draft.
    assert "dictate" not in body["draft"]["body"].lower()


# ---------------------------------------------------------------------------
# Bug 4 — plural "mails"/"emails" and trailing punctuation in parse_command
# ---------------------------------------------------------------------------


def test_parse_command_plural_mails():
    assert parse_command("read my unread mails") == "READ_INBOX"


def test_parse_command_plural_emails():
    assert parse_command("check my emails") == "READ_INBOX"


def test_parse_command_tolerates_trailing_period():
    assert parse_command("read my unread mail.") == "READ_INBOX"


def test_parse_command_tolerates_trailing_question_mark():
    assert parse_command("send?") == "SEND"


def test_read_unread_mails_route_level_matches_inbox_not_ai(client):
    resp = client.post(
        "/api/turn", json={"session_id": "bug4-route", "transcript": "read my unread mails"}
    )
    body = resp.json()
    assert body["phase"] == "reading_inbox"
    assert "unread message" in body["speech"]
