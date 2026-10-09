"""F58 — "use my usual sign-off" (PHASE_10_PLUS_SPEC.md §13.3)."""

from backend.data.prefs import record_signoff_phrase, top_signoff_phrase
from backend.speechify import read_last_lines


def test_record_and_top_signoff_round_trip():
    assert top_signoff_phrase() is None
    record_signoff_phrase("Thanks, Vidur")
    assert top_signoff_phrase() == "Thanks, Vidur"


def test_top_signoff_ranks_by_use_count():
    record_signoff_phrase("Best regards")
    record_signoff_phrase("Thanks, Vidur")
    record_signoff_phrase("Thanks, Vidur")
    assert top_signoff_phrase() == "Thanks, Vidur"


def test_record_signoff_skips_empty_and_overlong():
    record_signoff_phrase("")
    record_signoff_phrase("x" * 61)
    assert top_signoff_phrase() is None


def test_read_last_lines_default_two():
    body = "Hi John,\n\nI will be there at five.\n\nThanks,\nVidur"
    assert read_last_lines(body) == "Thanks, Vidur"


def test_read_last_lines_empty_body():
    assert read_last_lines("") == "an empty message"


# ---------------------------------------------------------------------------
# Route-level
# ---------------------------------------------------------------------------


def test_use_signoff_with_nothing_learned_yet(client):
    session_id = "signoff-none"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"})
    resp = client.post("/api/turn", json={"session_id": session_id, "transcript": "use my usual sign-off"})
    body = resp.json()
    assert body["speech"] == (
        "I haven't learned a sign-off from you yet. Dictate one at the end of a message and I'll remember it."
    )


def test_use_signoff_appends_learned_phrase_and_undo_reverts(client):
    # First send: dictate a body with "new paragraph" so the sign-off ends
    # up on its own line (_extract_signoff takes the last NEWLINE-
    # separated line, not the last sentence).
    session_id = "signoff-learn"
    client.post(
        "/api/turn",
        json={
            "session_id": session_id,
            "transcript": "tell John Smith I will be late new paragraph Thanks, Vidur",
        },
    )
    client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})

    # Second, fresh draft: apply the learned sign-off via the command.
    session_id_2 = "signoff-use"
    client.post(
        "/api/turn", json={"session_id": session_id_2, "transcript": "tell Sarah Lee the report is ready"}
    )
    before = client.post(
        "/api/turn", json={"session_id": session_id_2, "transcript": "read it back"}
    ).json()["draft"]["body"]

    resp = client.post(
        "/api/turn", json={"session_id": session_id_2, "transcript": "use my usual sign-off"}
    )
    body = resp.json()
    assert "Thanks, Vidur" in body["draft"]["body"]
    assert body["draft"]["body"] != before
    assert "Thanks, Vidur" in body["speech"]

    undone = client.post("/api/turn", json={"session_id": session_id_2, "transcript": "undo"}).json()
    assert undone["draft"]["body"] == before


def test_use_signoff_refused_without_a_draft(client):
    resp = client.post(
        "/api/turn", json={"session_id": "signoff-no-draft", "transcript": "use my usual sign-off"}
    )
    body = resp.json()
    assert "only available" in body["speech"]
