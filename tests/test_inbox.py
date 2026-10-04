"""Phase 6 — reading mail. Offline only (FAKE_GMAIL=1/FAKE_AI=1, set by
conftest.py) — no real Gmail API call, no network access anywhere.
"""

from backend.gmail import fake
from backend.gmail.inbox import _extract_plain_text, _parse_addresses, get_my_email

FORBIDDEN_SUBSTRINGS = ["{", "}", "None", "null", "Traceback"]


def _assert_speech_is_clean(speech: str) -> None:
    assert speech
    for bad in FORBIDDEN_SUBSTRINGS:
        assert bad not in speech


# ---------------------------------------------------------------------------
# _extract_plain_text — pure function, no network
# ---------------------------------------------------------------------------


def _body(text: str) -> dict:
    import base64

    return {"data": base64.urlsafe_b64encode(text.encode()).decode()}


def test_extract_plain_text_plain_only():
    payload = {"mimeType": "text/plain", "body": _body("Hello there.")}
    assert _extract_plain_text(payload) == "Hello there."


def test_extract_plain_text_html_only():
    payload = {"mimeType": "text/html", "body": _body("<p>Hello <b>there</b>.</p>")}
    assert _extract_plain_text(payload) == "Hello there ."


def test_extract_plain_text_empty_or_malformed_body():
    assert _extract_plain_text({"mimeType": "text/plain", "body": {}}) == ""
    assert _extract_plain_text({}) == ""
    # Bad padding -> binascii.Error (a ValueError subclass) -> caught, not raised.
    assert _extract_plain_text({"mimeType": "text/plain", "body": {"data": "abc"}}) == ""


def test_extract_plain_text_mixed_branches_never_drops_html_only_branch():
    """Phase 6 bug #3: a multipart/mixed message with TWO
    multipart/alternative children — the first has both plain and html,
    the second has ONLY html (e.g. quoted history). A global "prefer
    plain text anywhere in the message" rule would let the first
    branch's plain text hide the second branch's content entirely. Each
    multipart/alternative must resolve independently.
    """
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": _body("Plain reply text.")},
                    {"mimeType": "text/html", "body": _body("<p>Plain reply text.</p>")},
                ],
            },
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/html", "body": _body("<p>Quoted history only.</p>")},
                ],
            },
        ],
    }
    text = _extract_plain_text(payload)
    assert "Plain reply text." in text
    assert "Quoted history only." in text


# ---------------------------------------------------------------------------
# Fake inbox functions, called directly
# ---------------------------------------------------------------------------


def test_fake_list_unread_returns_seed_items():
    items = fake.fake_list_unread(10)
    assert len(items) == 3
    assert all(item.unread for item in items)


def test_fake_list_unread_respects_limit():
    items = fake.fake_list_unread(1)
    assert len(items) == 1


def test_fake_get_thread_context_returns_body_and_message_id():
    items = fake.fake_list_unread(10)
    context = fake.fake_get_thread_context(items[0].thread_id)
    assert context.text
    assert context.last_message_id_header


def test_fake_get_thread_context_unknown_thread_is_empty():
    context = fake.fake_get_thread_context("no-such-thread")
    assert context.text == ""
    assert context.last_message_id_header is None


def test_fake_archive_removes_from_unread_listing():
    items = fake.fake_list_unread(10)
    first_id = items[0].id
    result = fake.fake_archive(first_id)
    assert result.success is True
    remaining = fake.fake_list_unread(10)
    assert all(item.id != first_id for item in remaining)


def test_fake_mark_read_removes_from_unread_listing():
    items = fake.fake_list_unread(10)
    first_id = items[0].id
    fake.fake_mark_read(first_id)
    remaining = fake.fake_list_unread(10)
    assert all(item.id != first_id for item in remaining)


# ---------------------------------------------------------------------------
# Route-level gate sequence, through /api/turn
# ---------------------------------------------------------------------------


def test_read_inbox_lists_all_three(client):
    resp = client.post("/api/turn", json={"session_id": "inbox-1", "transcript": "read my unread mail"})
    body = resp.json()
    _assert_speech_is_clean(body["speech"])
    assert body["phase"] == "reading_inbox"
    assert "3 unread messages" in body["speech"]
    assert "Priya Nair" in body["speech"]


def test_full_gate_sequence(client):
    session_id = "inbox-gate"

    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    assert r1.json()["phase"] == "reading_inbox"

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    assert "David Chen" in b2["speech"]

    r3 = client.post("/api/turn", json={"session_id": session_id, "transcript": "who is it from"})
    assert "David Chen" in r3.json()["speech"]

    r4 = client.post("/api/turn", json={"session_id": session_id, "transcript": "summarise this one"})
    _assert_speech_is_clean(r4.json()["speech"])

    r5 = client.post("/api/turn", json={"session_id": session_id, "transcript": "archive this"})
    b5 = r5.json()
    _assert_speech_is_clean(b5["speech"])
    assert "Archived" in b5["speech"]
    assert b5["phase"] == "reading_inbox"  # 2 items still left

    r6 = client.post("/api/turn", json={"session_id": session_id, "transcript": "reply"})
    b6 = r6.json()
    _assert_speech_is_clean(b6["speech"])
    assert b6["phase"] == "review"

    r7 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "sounds good, see you then"}
    )
    b7 = r7.json()
    _assert_speech_is_clean(b7["speech"])
    assert b7["phase"] == "awaiting_confirm"
    assert b7["draft"]["body"]

    r8 = client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})
    b8 = r8.json()
    assert b8["ok"] is True
    assert "Sent to" in b8["speech"]
    assert b8["phase"] == "idle"


def test_read_inbox_blocked_mid_draft(client):
    session_id = "inbox-guard"
    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    assert r1.json()["phase"] == "awaiting_confirm"

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    b2 = r2.json()
    _assert_speech_is_clean(b2["speech"])
    # The draft must still be there afterward — nothing was silently discarded.
    assert b2["phase"] == "awaiting_confirm"
    assert b2["draft"]["recipient_name"] == "John Smith"


def test_inbox_commands_without_open_inbox_give_clear_message(client):
    resp = client.post("/api/turn", json={"session_id": "inbox-none", "transcript": "next email"})
    body = resp.json()
    _assert_speech_is_clean(body["speech"])
    assert "inbox" in body["speech"].lower()


def test_next_email_at_boundary(client):
    session_id = "inbox-boundary"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})
    assert r.json()["speech"] == "That's the last message."


def test_previous_email_at_boundary(client):
    session_id = "inbox-boundary-prev"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "previous email"})
    assert r.json()["speech"] == "That's the first message."


# ---------------------------------------------------------------------------
# Archive boundary cases (Phase 6 bug #4) — archiving the LAST item, and
# archiving all the way down to an empty inbox, not just a middle one.
# ---------------------------------------------------------------------------


def test_archive_the_last_item_in_a_longer_list(client):
    session_id = "inbox-archive-last"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})  # now at index 2 (last)

    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "archive this"})
    body = r.json()
    _assert_speech_is_clean(body["speech"])
    assert "Archived" in body["speech"]
    assert body["phase"] == "reading_inbox"


def test_archive_down_to_empty_inbox(client):
    session_id = "inbox-archive-empty"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})

    client.post("/api/turn", json={"session_id": session_id, "transcript": "archive this"})
    client.post("/api/turn", json={"session_id": session_id, "transcript": "archive this"})
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "archive this"})
    body = r.json()
    _assert_speech_is_clean(body["speech"])
    assert body["phase"] == "idle"
    assert "empty" in body["speech"].lower()

    # And the phase is genuinely reset — inbox commands now say there's
    # nothing open, rather than crashing on an empty list.
    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "next email"})
    assert "inbox" in r2.json()["speech"].lower()


def test_mark_as_read_explicit_command(client):
    session_id = "inbox-mark-read"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "mark as read"})
    body = r.json()
    _assert_speech_is_clean(body["speech"])
    assert body["speech"] == "Marked as read."


def test_read_full_message(client):
    session_id = "inbox-read-full"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "read my unread mail"})
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "read it in full"})
    body = r.json()
    _assert_speech_is_clean(body["speech"])
    assert len(body["speech"]) > len("From Priya Nair.")


# ---------------------------------------------------------------------------
# Completeness pass (F36 reply-all): _parse_addresses, get_my_email
# ---------------------------------------------------------------------------


def test_parse_addresses_handles_plain_list():
    addrs = _parse_addresses("Alex Kim <alex.kim@example.com>, David Chen <david.chen@example.com>")
    assert addrs == ["alex.kim@example.com", "david.chen@example.com"]


def test_parse_addresses_handles_quoted_comma_in_display_name():
    # Verified via the Plan agent directly against the installed stdlib —
    # a naive .split(",") would wrongly produce 3 pieces here, not 2.
    addrs = _parse_addresses('"Kim, Alex" <alex.kim@example.com>, David Chen <david.chen@example.com>')
    assert addrs == ["alex.kim@example.com", "david.chen@example.com"]


def test_parse_addresses_handles_bare_address_with_no_display_name():
    addrs = _parse_addresses("alex.kim@example.com, David Chen <david.chen@example.com>")
    assert addrs == ["alex.kim@example.com", "david.chen@example.com"]


def test_parse_addresses_empty_header_returns_empty_list():
    assert _parse_addresses("") == []


def test_get_my_email_fake_mode_returns_fixed_address():
    assert get_my_email() == "me@example.com"
