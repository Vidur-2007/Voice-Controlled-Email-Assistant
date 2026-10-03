from backend.gmail import fake
from backend.models import Draft
from tests.conftest import read_outbox_lines


def test_fake_send_writes_well_formed_outbox_line():
    draft = Draft(
        recipient="john@example.com",
        recipient_name="John",
        subject="Running late",
        body="I will be late.",
    )
    result = fake.fake_send(draft)
    assert result.success is True
    assert result.message[-1] in ".!?"

    lines = read_outbox_lines()
    assert len(lines) == 1
    assert lines[0]["type"] == "send"
    assert lines[0]["recipient"] == "john@example.com"
    assert lines[0]["subject"] == "Running late"
    assert lines[0]["body"] == "I will be late."
    assert "timestamp" in lines[0]


def test_fake_send_invalid_recipient_fails_without_writing():
    draft = Draft(recipient="", subject="x", body="y")
    result = fake.fake_send(draft)
    assert result.success is False
    assert result.message == (
        "That address doesn't look right, so I haven't sent it. "
        "Say 'change recipient' to fix it."
    )
    assert read_outbox_lines() == []


def test_fake_save_draft_writes_draft_type_line():
    draft = Draft(recipient="john@example.com", subject="x", body="y")
    result = fake.fake_save_draft(draft)
    assert result.success is True

    lines = read_outbox_lines()
    assert lines[-1]["type"] == "draft"


def test_fake_send_records_attachments_and_send_at():
    draft = Draft(
        recipient="john@example.com",
        subject="x",
        body="y",
        attachments=["/tmp/x/invoice.pdf"],
        send_at="2026-09-28T17:00:00",
    )
    fake.fake_send(draft)
    lines = read_outbox_lines()
    assert lines[-1]["attachments"] == ["/tmp/x/invoice.pdf"]
    assert lines[-1]["send_at"] == "2026-09-28T17:00:00"
