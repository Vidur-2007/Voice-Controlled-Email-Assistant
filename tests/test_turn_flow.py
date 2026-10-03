"""A full scripted conversation through /api/turn (§29's required test)."""

FORBIDDEN_SUBSTRINGS = ["{", "}", "None", "null", "Traceback"]


def _assert_speech_is_clean(speech: str) -> None:
    assert speech
    for bad in FORBIDDEN_SUBSTRINGS:
        assert bad not in speech


def test_empty_transcript(client):
    resp = client.post("/api/turn", json={"session_id": "flow-1", "transcript": ""})
    body = resp.json()
    _assert_speech_is_clean(body["speech"])
    assert body["speech"] == "I didn't catch that. Could you say it again?"
    assert body["ok"] is True


def test_full_conversation_compose_readback_send(client):
    session_id = "flow-2"

    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    b1 = r1.json()
    _assert_speech_is_clean(b1["speech"])
    assert b1["phase"] == "awaiting_confirm"
    assert b1["awaiting_confirmation"] is True
    assert "To John Smith." in b1["speech"]
    assert "Subject:" in b1["speech"]
    assert "Message:" in b1["speech"]

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "make it shorter"})
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    # "make it shorter" (F21/§22) is a real edit now — it genuinely
    # shortens the draft's body and stays in awaiting_confirm afterward.
    assert b2["phase"] == "awaiting_confirm"
    assert b2["draft"]["body"] != b1["draft"]["body"]
    assert b2["draft"]["recipient_name"] == "John Smith"

    r3 = client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
    b3 = r3.json()
    _assert_speech_is_clean(b3["speech"])
    assert b3["ok"] is True
    assert "Sent to John Smith" in b3["speech"]
    assert b3["phase"] == "idle"


def test_shorter_then_formal_then_undo(client):
    """The Phase 3 gate scenario, fully offline (FAKE_AI=1).

    Assertions are on the JSON `draft` fields rather than spoken text for
    the tone step deliberately: in fake mode a tone change doesn't reword
    the body (real Ollama does), so `build_readback()`'s spoken output is
    identical before/after that specific step — a documented
    interpretation, not an oversight.
    """
    session_id = "flow-11"

    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    original_body = r1.json()["draft"]["body"]
    assert r1.json()["phase"] == "awaiting_confirm"

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "make it shorter"})
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    assert b2["draft"]["body"] != original_body
    assert b2["draft"]["length"] == "short"
    shortened_body = b2["draft"]["body"]

    r3 = client.post("/api/turn", json={"session_id": session_id, "transcript": "make it more formal"})
    b3 = r3.json()
    _assert_speech_is_clean(b3["speech"])
    assert b3["draft"]["tone"] == "formal"
    assert b3["draft"]["recipient_name"] == "John Smith"  # untouched by the edit
    assert b3["draft"]["subject"] == r1.json()["draft"]["subject"]  # untouched

    r4 = client.post("/api/turn", json={"session_id": session_id, "transcript": "undo"})
    b4 = r4.json()
    _assert_speech_is_clean(b4["speech"])
    assert b4["speech"].startswith("Undone.")
    assert "To John Smith." in b4["speech"]
    assert b4["draft"]["tone"] == "neutral"  # back to pre-formal
    assert b4["draft"]["body"] == shortened_body  # still shortened — only the formal edit was undone


def test_undo_with_nothing_to_undo(client):
    session_id = "flow-12"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "undo"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["speech"] == "There's nothing to undo."


def test_send_before_compose_is_refused(client):
    r = client.post("/api/turn", json={"session_id": "flow-3", "transcript": "send"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["speech"] == "I haven't read the message back to you yet. Say 'read it back' first."


def test_cancel_clears_draft(client):
    session_id = "flow-4"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "cancel"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["phase"] == "idle"
    assert "Cancelled" in b["speech"]


def test_restart_clears_draft(client):
    session_id = "flow-5"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "start over"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["phase"] == "idle"


def test_repeat_rereads_the_draft(client):
    session_id = "flow-6"
    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "read it back"})
    assert r2.json()["speech"] == r1.json()["speech"]


def test_help_at_idle(client):
    r = client.post("/api/turn", json={"session_id": "flow-7", "transcript": "help"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert len(b["speech"]) > 0


def test_read_subject_body_recipient_at_awaiting_confirm(client):
    session_id = "flow-9"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )

    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "read the subject"})
    b1 = r1.json()
    _assert_speech_is_clean(b1["speech"])
    assert b1["speech"].startswith("The subject is:")
    assert b1["phase"] == "awaiting_confirm"

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "read the body"})
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    assert "late" in b2["speech"].lower()

    r3 = client.post("/api/turn", json={"session_id": session_id, "transcript": "who is it going to"})
    b3 = r3.json()
    _assert_speech_is_clean(b3["speech"])
    assert b3["speech"] == "This is going to John Smith."


def test_read_subject_refused_without_a_draft(client):
    r = client.post("/api/turn", json={"session_id": "flow-10", "transcript": "read the subject"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["speech"] == "There's no message to read yet."


def test_mode_override_standalone_then_content(client):
    session_id = "flow-13"

    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "dictate this"})
    b1 = r1.json()
    _assert_speech_is_clean(b1["speech"])
    assert b1["phase"] == "idle"  # still idle — waiting for the actual content next turn

    r2 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    assert b2["phase"] == "awaiting_confirm"
    assert "To John Smith." in b2["speech"]


def test_ambiguous_mode_asks_then_composes(client):
    session_id = "flow-14"
    # 20 words: inside the "ask the model" zone, but under FAKE_AI=1 the
    # heuristic zone itself resolves without asking — use enough words to
    # land in the zone and confirm behavior either way is self-consistent.
    transcript = "let " + " ".join(["everyone"] * 19)

    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": transcript})
    b1 = r1.json()
    _assert_speech_is_clean(b1["speech"])
    # Under FAKE_AI=1 this always resolves directly (no ask) — confirm it
    # reaches a sensible phase either way (awaiting_confirm or
    # awaiting_address, never left dangling).
    assert b1["phase"] in ("awaiting_confirm", "awaiting_address", "awaiting_mode")

    if b1["phase"] == "awaiting_mode":
        r2 = client.post(
            "/api/turn", json={"session_id": session_id, "transcript": "write it for me"}
        )
        b2 = r2.json()
        _assert_speech_is_clean(b2["speech"])
        assert b2["phase"] in ("awaiting_confirm", "awaiting_address")


def test_no_recipient_asks_who(client):
    session_id = "flow-8"
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "I need help with the report"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["phase"] == "awaiting_address"
    assert b["speech"] == "Who should I send this to?"

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "Priya"})
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    assert b2["phase"] == "awaiting_confirm"
    assert "To Priya." in b2["speech"]


# ---------------------------------------------------------------------------
# Phase 7 — mid-speech correction, "new paragraph", CC, attach, schedule
# ---------------------------------------------------------------------------


def test_mid_speech_correction_during_compose(client):
    session_id = "flow-correction"
    r = client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "transcript": "tell John Smith I'll call at 5, no wait, tell John Smith I will call at 6",
        },
    )
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["phase"] == "awaiting_confirm"
    assert "6" in b["draft"]["body"]
    assert "5" not in b["draft"]["body"]


def test_new_paragraph_creates_a_pause_in_the_body(client):
    session_id = "flow-paragraph"
    r = client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "transcript": "tell John Smith I will be there at five new paragraph thanks",
        },
    )
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert "\n\n" in b["draft"]["body"]


def test_add_cc_via_voice_turn(client):
    session_id = "flow-cc"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "copy in Sarah"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert "Copying Sarah Lee." in b["speech"]
    assert b["draft"]["cc"] == ["sarah.lee@example.com"]
    assert b["draft"]["cc_names"] == ["Sarah Lee"]


def test_add_cc_ambiguous_name_fails_cleanly_without_a_second_clarifying_phase(client):
    session_id = "flow-cc-ambiguous"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell Sarah Lee I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "copy in John"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert "couldn't tell who you meant" in b["speech"]
    assert b["phase"] == "awaiting_confirm"  # never opens a second clarifying sub-conversation
    assert b["draft"]["cc"] == []


def test_add_cc_bare_phrase_gives_instructions(client):
    session_id = "flow-cc-bare"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "add cc"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert "add cc" in b["speech"].lower()


def test_attach_command_points_to_the_button(client):
    session_id = "flow-attach-focus"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "attach a file"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["focus_target"] == "attach-btn"


def test_attach_file_via_route_then_readback_mentions_it(client):
    session_id = "flow-attach"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )

    upload = client.post(
        "/api/mail/attachment",
        data={"session_id": session_id},
        files={"file": ("invoice.pdf", b"pdf bytes", "application/pdf")},
    )
    assert upload.json()["success"] is True

    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "read it back"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert "one attachment: invoice.pdf" in b["speech"]
    assert b["draft"]["attachments"]


def test_attach_last_with_nothing_attached_gives_clear_fallback(client):
    session_id = "flow-attach-last-empty"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "attach the last document i mentioned"}
    )
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert "haven't attached anything" in b["speech"]
    assert b["focus_target"] == "attach-btn"


def test_attach_last_reuses_file_across_drafts_in_the_same_session(client):
    """The whole point of tracking "last attachment" outside
    ConversationState: it must survive a reset_session() (here, a
    successful send) so a second draft in the same session can reuse it.
    """
    session_id = "flow-attach-last"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    client.post(
        "/api/mail/attachment",
        data={"session_id": session_id},
        files={"file": ("invoice.pdf", b"pdf bytes", "application/pdf")},
    )
    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
    assert r1.json()["ok"] is True
    assert r1.json()["phase"] == "idle"

    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell Sarah Lee thanks"})
    r2 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "attach the last document i mentioned"}
    )
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    assert "invoice.pdf" in b2["speech"]
    assert b2["draft"]["attachments"]


def test_schedule_via_voice_turn_resolves_and_inserts_a_row(client):
    from backend.data.store import get_connection

    session_id = "flow-schedule"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "schedule this for 5pm"})
    b = r.json()
    _assert_speech_is_clean(b["speech"])
    assert b["ok"] is True
    assert b["phase"] == "idle"  # reset on success, same as SEND
    assert "Okay, I'll send this" in b["speech"]

    rows = get_connection().execute("SELECT sent FROM scheduled").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == 0


def test_schedule_ambiguous_time_asks_then_resolves(client):
    session_id = "flow-schedule-ambiguous"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "schedule this for 5"})
    b1 = r1.json()
    _assert_speech_is_clean(b1["speech"])
    assert b1["phase"] == "awaiting_schedule_time"
    assert "AM" in b1["speech"] and "PM" in b1["speech"]

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "5 PM"})
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    assert b2["ok"] is True
    assert b2["phase"] == "idle"


def test_cc_attach_schedule_all_refused_outside_awaiting_confirm(client):
    for transcript in ("copy in Sarah", "attach a file", "attach the last document i mentioned", "send this at 5pm"):
        r = client.post(
            "/api/turn", json={"session_id": f"flow-guard-{transcript}", "transcript": transcript}
        )
        b = r.json()
        _assert_speech_is_clean(b["speech"])
        assert "only available" in b["speech"]
