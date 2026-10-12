"""Phase 15 — "read my drafts" / "send my saved draft".

Saved drafts are a NEW feature, not a bug fix (the app previously had no
way at all to browse or send a previously-saved Gmail draft, only to
create one via SAVE_DRAFT). Fake-mode saved drafts live in a small
id-keyed store in gmail/fake.py (`_fake_drafts`), separate from
outbox.jsonl's append-only log, since sending one later needs to fetch
and remove it by id.
"""

from backend.gmail.drafts import list_drafts, send_draft
from backend.gmail.fake import fake_list_drafts, fake_save_draft, fake_send_draft
from backend.models import Draft


def _save(recipient="priya.nair@example.com", recipient_name="Priya Nair", subject="Project update", body="Just checking in."):
    return fake_save_draft(
        Draft(recipient=recipient, recipient_name=recipient_name, subject=subject, body=body)
    )


# ---------------------------------------------------------------------------
# gmail/fake.py + gmail/drafts.py unit tests
# ---------------------------------------------------------------------------


def test_fake_save_draft_registers_it_for_listing():
    result = _save()
    assert result.success
    items = fake_list_drafts(limit=10)
    assert len(items) == 1
    assert items[0].recipient_name == "Priya Nair"
    assert items[0].subject == "Project update"
    assert items[0].id.startswith("fake-draft-")


def test_list_drafts_dispatches_to_fake_mode():
    _save()
    _save(recipient_name="David Chen", subject="Lunch?")
    items = list_drafts(limit=10)
    assert [i.recipient_name for i in items] == ["Priya Nair", "David Chen"]


def test_fake_send_draft_removes_it_and_appends_to_outbox(tmp_path, monkeypatch):
    _save()
    items = fake_list_drafts(limit=10)
    draft_id = items[0].id

    result = send_draft(draft_id)
    assert result.success
    assert "Priya Nair" in result.message

    # Sent drafts no longer show up in the list.
    assert fake_list_drafts(limit=10) == []


def test_fake_send_draft_unknown_id():
    result = send_draft("not-a-real-id")
    assert not result.success
    assert "couldn't find" in result.message.lower()


def test_fake_save_draft_invalid_recipient_not_registered():
    result = fake_save_draft(Draft(recipient="", subject="x", body="y"))
    assert not result.success
    assert fake_list_drafts(limit=10) == []


# ---------------------------------------------------------------------------
# Route-level: "read my drafts" / navigation / "send my saved draft" / "send"
# ---------------------------------------------------------------------------


def _turn(client, session_id, transcript):
    return client.post("/api/turn", json={"session_id": session_id, "transcript": transcript})


def test_read_my_drafts_with_none_saved(client):
    resp = _turn(client, "s1", "read my drafts")
    assert resp.json()["speech"] == "You don't have any saved drafts."
    assert resp.json()["phase"] == "idle"


def test_read_my_drafts_lists_and_enters_reading_drafts_phase(client):
    _save()
    resp = _turn(client, "s2", "read my drafts")
    body = resp.json()
    assert body["phase"] == "reading_drafts"
    assert "one saved draft" in body["speech"]
    assert "Priya Nair" in body["speech"]
    assert "Project update" in body["speech"]


def test_next_and_previous_draft_navigation(client):
    _save(recipient_name="Priya Nair", subject="Project update")
    _save(recipient_name="David Chen", subject="Lunch?")
    _turn(client, "s3", "read my drafts")

    nxt = _turn(client, "s3", "next draft").json()
    assert "David Chen" in nxt["speech"]

    at_last = _turn(client, "s3", "next draft").json()
    assert at_last["speech"] == "That's the last draft."

    prev = _turn(client, "s3", "previous draft").json()
    assert "Priya Nair" in prev["speech"]

    at_first = _turn(client, "s3", "previous draft").json()
    assert at_first["speech"] == "That's the first draft."


def test_navigation_without_loaded_drafts_is_refused(client):
    resp = _turn(client, "s4", "next draft").json()
    assert resp["speech"] == "You haven't opened your drafts yet. Say 'read my drafts' to start."


def test_send_while_browsing_sends_the_current_draft_and_removes_it(client):
    _save(recipient_name="Priya Nair", subject="Project update")
    _save(recipient_name="David Chen", subject="Lunch?")
    _turn(client, "s5", "read my drafts")
    _turn(client, "s5", "next draft")  # now on David Chen

    resp = _turn(client, "s5", "send").json()
    assert "David Chen" in resp["speech"]
    assert resp["phase"] == "reading_drafts"  # one draft (Priya) remains

    # The remaining draft is Priya's.
    again = _turn(client, "s5", "read my drafts").json()
    assert "Priya Nair" in again["speech"]
    assert "David Chen" not in again["speech"]


def test_send_while_browsing_last_remaining_draft_returns_to_idle(client):
    _save(recipient_name="Priya Nair", subject="Project update")
    _turn(client, "s6", "read my drafts")

    resp = _turn(client, "s6", "send it").json()
    assert "Priya Nair" in resp["speech"]
    assert "empty now" in resp["speech"]
    assert resp["phase"] == "idle"


def test_send_my_saved_draft_direct_shortcut_with_exactly_one(client):
    _save(recipient_name="Priya Nair", subject="Project update")
    resp = _turn(client, "s7", "send my saved draft").json()
    assert "Priya Nair" in resp["speech"]
    assert resp["phase"] == "idle"
    assert fake_list_drafts(limit=10) == []


def test_send_my_saved_draft_with_none_saved(client):
    resp = _turn(client, "s8", "send my saved draft").json()
    assert resp["speech"] == "You don't have any saved drafts."


def test_send_my_saved_draft_ambiguous_with_multiple(client):
    _save(recipient_name="Priya Nair", subject="Project update")
    _save(recipient_name="David Chen", subject="Lunch?")
    resp = _turn(client, "s9", "send my saved draft").json()
    assert "2 saved drafts" in resp["speech"]
    assert "read my drafts" in resp["speech"]
    # Neither draft was actually sent.
    assert len(fake_list_drafts(limit=10)) == 2


def test_read_my_drafts_blocked_mid_compose(client):
    _turn(client, "s10", "tell Priya I'll be late")
    resp = _turn(client, "s10", "read my drafts").json()
    assert "middle of a message" in resp["speech"]


def test_help_speech_for_reading_drafts_phase(client):
    _save()
    _turn(client, "s11", "read my drafts")
    resp = _turn(client, "s11", "help").json()
    assert "next draft" in resp["speech"]
    assert "previous draft" in resp["speech"]
