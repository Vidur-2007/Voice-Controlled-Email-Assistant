import pytest
from pydantic import ValidationError

from backend.models import (
    ContactCandidate,
    Draft,
    InboxItem,
    MailResult,
    TurnRequest,
    TurnResponse,
)


def test_draft_defaults_are_never_none():
    d = Draft()
    assert d.recipient == ""
    assert d.subject == ""
    assert d.body == ""
    assert d.recipient_name == ""
    assert d.cc == []
    assert d.bcc == []
    assert d.attachments == []
    assert d.tone == "neutral"
    assert d.length == "normal"
    assert d.thread_id is None
    assert d.send_at is None


def test_turn_request_requires_nonempty_session_id():
    with pytest.raises(ValidationError):
        TurnRequest(session_id="")

    req = TurnRequest(session_id="abc")
    assert req.transcript == ""


def test_turn_response_defaults():
    resp = TurnResponse(speech="hello")
    assert resp.phase == "idle"
    assert resp.awaiting_confirmation is False
    assert resp.listen_again is True
    assert resp.ok is True
    assert resp.draft is None


def test_mail_result_message_ends_in_punctuation():
    result = MailResult(success=True, message="Sent.")
    assert result.success is True
    assert result.message[-1] in ".!?"


def test_contact_candidate_defaults():
    c = ContactCandidate(name="John", email="john@example.com")
    assert c.score == 0.0


def test_inbox_item_defaults_unread_true():
    item = InboxItem(
        id="1",
        thread_id="t1",
        sender_name="A",
        sender_email="a@x.com",
        subject="s",
        snippet="sn",
    )
    assert item.unread is True
