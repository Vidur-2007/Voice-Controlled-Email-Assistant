"""Offline tests for backend/gmail/send.py and backend/gmail/auth.py — no
real Gmail API call, no real OAuth flow, no network access anywhere.
"""

import base64
import json

import pytest
from googleapiclient.errors import HttpError

from backend.errors import SpokenError
from backend.gmail import auth, send
from backend.models import Draft


# ---------------------------------------------------------------------------
# _build_message_payload — pure function, no network
# ---------------------------------------------------------------------------


def _decode_raw(payload: dict) -> bytes:
    return base64.urlsafe_b64decode(payload["raw"].encode())


def test_build_message_payload_headers_and_body():
    draft = Draft(
        recipient="john.smith@example.com",
        subject="Running late",
        body="I will be late.",
        cc=["sarah@example.com"],
        bcc=["alex@example.com"],
    )
    payload = send._build_message_payload(draft)

    raw_bytes = _decode_raw(payload)
    assert b"To: john.smith@example.com" in raw_bytes
    assert b"Subject: Running late" in raw_bytes
    assert b"Cc: sarah@example.com" in raw_bytes
    assert b"Bcc: alex@example.com" in raw_bytes
    assert b"I will be late." in raw_bytes


def test_build_message_payload_omits_cc_bcc_when_empty():
    draft = Draft(recipient="john@example.com", subject="Hi", body="Hello.")
    payload = send._build_message_payload(draft)
    raw_bytes = _decode_raw(payload)
    assert b"Cc:" not in raw_bytes
    assert b"Bcc:" not in raw_bytes


def test_build_message_payload_thread_id_is_sibling_not_nested():
    """The spec explicitly calls this asymmetry out as a common bug:
    threadId sits beside "raw", never nested inside it.
    """
    draft = Draft(recipient="john@example.com", subject="Re: Hi", body="Reply.", thread_id="thread123")
    payload = send._build_message_payload(draft)
    assert payload["threadId"] == "thread123"
    assert "raw" in payload
    assert set(payload.keys()) == {"raw", "threadId"}


def test_build_message_payload_no_thread_id_when_none():
    draft = Draft(recipient="john@example.com", subject="Hi", body="Hello.")
    payload = send._build_message_payload(draft)
    assert "threadId" not in payload


# ---------------------------------------------------------------------------
# _build_message_payload — attachments (F30)
# ---------------------------------------------------------------------------


def test_build_message_payload_with_attachment_is_multipart(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"%PDF-1.4 fake pdf content")

    draft = Draft(recipient="john@example.com", subject="Hi", body="See attached.", attachments=[str(path)])
    payload = send._build_message_payload(draft)
    raw_bytes = _decode_raw(payload)

    assert b"multipart/mixed" in raw_bytes
    assert b'filename="invoice.pdf"' in raw_bytes
    assert b"See attached." in raw_bytes


def test_build_message_payload_unknown_extension_falls_back_to_octet_stream(tmp_path):
    path = tmp_path / "mystery.xyz123"
    path.write_bytes(b"binary-ish content")

    draft = Draft(recipient="john@example.com", subject="Hi", body="See attached.", attachments=[str(path)])
    payload = send._build_message_payload(draft)
    raw_bytes = _decode_raw(payload)

    assert b"application/octet-stream" in raw_bytes


def test_build_message_payload_multiple_attachments(tmp_path):
    path_a = tmp_path / "a.txt"
    path_a.write_bytes(b"aaa")
    path_b = tmp_path / "b.txt"
    path_b.write_bytes(b"bbb")

    draft = Draft(
        recipient="john@example.com", subject="Hi", body="Two files.", attachments=[str(path_a), str(path_b)]
    )
    payload = send._build_message_payload(draft)
    raw_bytes = _decode_raw(payload)

    assert b'filename="a.txt"' in raw_bytes
    assert b'filename="b.txt"' in raw_bytes


def test_build_message_payload_single_part_when_no_attachments():
    draft = Draft(recipient="john@example.com", subject="Hi", body="Hello.")
    payload = send._build_message_payload(draft)
    raw_bytes = _decode_raw(payload)
    assert b"multipart" not in raw_bytes


# ---------------------------------------------------------------------------
# _is_valid_recipient
# ---------------------------------------------------------------------------


def test_is_valid_recipient():
    assert send._is_valid_recipient("john@example.com") is True
    assert send._is_valid_recipient("") is False
    assert send._is_valid_recipient("not-an-address") is False


# ---------------------------------------------------------------------------
# Real-path error mapping — mocked Gmail service, zero network calls
# ---------------------------------------------------------------------------


class _FakeHttpResponse:
    def __init__(self, status: int):
        self.status = status
        self.reason = "error"


def _http_error(status: int) -> HttpError:
    content = json.dumps({"error": {"message": "boom"}}).encode()
    return HttpError(_FakeHttpResponse(status), content, uri="https://gmail.googleapis.com/fake")


class _FailingExecute:
    def __init__(self, exc: Exception):
        self._exc = exc

    def execute(self):
        raise self._exc


class _FailingMessages:
    def __init__(self, exc: Exception):
        self._exc = exc

    def send(self, **kwargs):
        return _FailingExecute(self._exc)


class _FailingDrafts:
    def __init__(self, exc: Exception):
        self._exc = exc

    def create(self, **kwargs):
        return _FailingExecute(self._exc)


class _FailingUsers:
    def __init__(self, exc: Exception):
        self._exc = exc

    def messages(self):
        return _FailingMessages(self._exc)

    def drafts(self):
        return _FailingDrafts(self._exc)


class _FailingService:
    def __init__(self, exc: Exception):
        self._exc = exc

    def users(self):
        return _FailingUsers(self._exc)


def _draft() -> Draft:
    return Draft(recipient="john.smith@example.com", subject="Hi", body="Hello.")


def test_real_send_maps_403_to_permission_message(monkeypatch):
    monkeypatch.setattr(send, "_build_service", lambda: _FailingService(_http_error(403)))
    result = send._real_send(_draft())
    assert result.success is False
    assert result.message == (
        "Your email account refused the request, so nothing was sent. It may not have granted permission to send mail."
    )


def test_real_send_maps_429_to_busy_message(monkeypatch):
    monkeypatch.setattr(send, "_build_service", lambda: _FailingService(_http_error(429)))
    result = send._real_send(_draft())
    assert result.success is False
    assert result.message == "Your email provider is busy right now, so nothing was sent. Say 'send' once more to try again."


def test_real_save_draft_maps_500_to_busy_message(monkeypatch):
    monkeypatch.setattr(send, "_build_service", lambda: _FailingService(_http_error(500)))
    result = send._real_save_draft(_draft())
    assert result.success is False
    assert result.message == "Your email provider is busy right now, so nothing was sent. Say 'send' once more to try again."


def test_real_send_invalid_recipient_never_calls_the_service(monkeypatch):
    called = False

    def _boom():
        nonlocal called
        called = True
        raise AssertionError("should never be called for an invalid recipient")

    monkeypatch.setattr(send, "_build_service", _boom)
    result = send._real_send(Draft(recipient="", subject="Hi", body="Hello."))
    assert result.success is False
    assert result.message == send._INVALID_RECIPIENT_MESSAGE
    assert called is False


def test_real_send_success(monkeypatch):
    class _OkExecute:
        def execute(self):
            return {"id": "msg123"}

    class _OkMessages:
        def send(self, **kwargs):
            return _OkExecute()

    class _OkUsers:
        def messages(self):
            return _OkMessages()

    class _OkService:
        def users(self):
            return _OkUsers()

    monkeypatch.setattr(send, "_build_service", lambda: _OkService())
    result = send._real_send(Draft(recipient="john@example.com", recipient_name="John", subject="Hi", body="Hello."))
    assert result.success is True
    assert result.message == "Sent to John."


# ---------------------------------------------------------------------------
# auth.py — the missing-credentials-file pre-flight check
# ---------------------------------------------------------------------------


def test_missing_credentials_file_raises_spoken_error(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "_credentials_path", lambda: tmp_path / "does-not-exist.json")
    with pytest.raises(SpokenError) as exc_info:
        auth._run_interactive_flow()
    assert exc_info.value.message == (
        "I can't send mail yet because the email credentials file is missing, so nothing was sent."
    )


# ---------------------------------------------------------------------------
# Offline behavior — real "no internet" exceptions must get the specific
# spoken sentence, not the generic catch-all (they rarely contain the words
# "network" or "connection" in their text).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc_factory",
    [
        lambda: __import__("httplib2").ServerNotFoundError("Unable to find the server at gmail.googleapis.com"),
        lambda: __import__("socket").gaierror(11001, "getaddrinfo failed"),
        lambda: TimeoutError("timed out"),
        lambda: ConnectionResetError("reset"),
    ],
)
def test_real_send_maps_network_down_to_specific_message(monkeypatch, exc_factory):
    monkeypatch.setattr(send, "_build_service", lambda: _FailingService(exc_factory()))
    result = send._real_send(_draft())
    assert result.success is False
    assert result.message == "I couldn't reach the internet, so nothing was sent. Your draft is safe."
