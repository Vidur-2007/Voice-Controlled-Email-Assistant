"""Phase 8 accessibility audit, made repeatable: forces every §30
error-table row through `errors.py::to_spoken()`, and separately pins
`provider.py`'s own five `SpokenError` messages — the ones a real user
actually hears for the "missing model API key"/"model rate limit" rows,
since every real provider.py failure wraps itself in a SpokenError before
it would ever reach errors.py's `_PATTERNS` substring table (`to_spoken()`
checks `isinstance(exc, SpokenError)` first and returns `.message` as-is).

Every case here is checked against §30's own closing rule: "every message
states whether the email was sent." No network calls.
"""

import pytest

from backend.ai import provider
from backend.errors import SpokenError, to_spoken

_STATES_OUTCOME_PHRASES = ("nothing was sent", "nothing has been sent", "haven't sent it")


def _states_the_outcome(message: str) -> bool:
    low = message.lower()
    return any(phrase in low for phrase in _STATES_OUTCOME_PHRASES)


# (row label, synthetic exception, expected exact spoken sentence) — one
# per §30 row, in the table's own order.
_ERROR_TABLE_ROWS = [
    (
        "no credentials.json",
        Exception("credentials.json not found at path"),
        "I can't send mail yet because the email credentials file is missing, so nothing was sent.",
    ),
    (
        "invalid or expired token",
        Exception("invalid_grant: token has expired"),
        "My access to your email has expired, so nothing was sent. Say 'reconnect my email' to sign in again.",
    ),
    (
        "http 401/403",
        Exception("403 Forbidden"),
        "Your email account refused the request, so nothing was sent. It may not have granted permission to send mail.",
    ),
    (
        "http 429 or 5xx",
        Exception("429 Too Many Requests"),
        "Your email provider is busy right now, so nothing was sent. Say 'send' once more to try again.",
    ),
    (
        "invalid recipient address",
        Exception("invalid recipient address supplied"),
        "That address doesn't look right, so I haven't sent it. Say 'change recipient' to fix it.",
    ),
    (
        "missing model api key",
        Exception("missing api key for provider"),
        "I can't write the email because the writing assistant isn't set up, so nothing was sent.",
    ),
    (
        "model rate limit",
        Exception("rate limit exceeded, try later"),
        "The writing assistant is busy right now, so nothing was sent. Say 'try again' in a moment.",
    ),
    (
        "network failure",
        ConnectionError("no route to host"),
        "I couldn't reach the internet, so nothing was sent. Your draft is safe.",
    ),
    (
        "anything else",
        Exception("totally unexpected internal failure"),
        "Something went wrong and nothing was sent. Your draft is safe. Say 'help' to hear what you can do.",
    ),
]


@pytest.mark.parametrize("label,exc,expected", _ERROR_TABLE_ROWS, ids=[row[0] for row in _ERROR_TABLE_ROWS])
def test_error_table_row_is_correctly_worded(label, exc, expected):
    assert to_spoken(exc) == expected


@pytest.mark.parametrize("label,exc,expected", _ERROR_TABLE_ROWS, ids=[row[0] for row in _ERROR_TABLE_ROWS])
def test_error_table_row_states_the_outcome(label, exc, expected):
    assert _states_the_outcome(expected), f"{label!r} doesn't state whether the email was sent: {expected!r}"


def test_to_spoken_returns_a_spokenerrors_message_verbatim():
    exc = SpokenError(provider._OLLAMA_NOT_RUNNING_MESSAGE)
    assert to_spoken(exc) == provider._OLLAMA_NOT_RUNNING_MESSAGE


# provider.py's own five messages — the ACTUAL text spoken for the
# "missing model API key"/"model rate limit" §30 rows in this real app
# (see module docstring for why the _PATTERNS table entries above never
# fire in practice).
_PROVIDER_MESSAGES = [
    ("retry failed twice", provider._RETRY_FAILED_MESSAGE),
    ("ollama not running", provider._OLLAMA_NOT_RUNNING_MESSAGE),
    ("ollama generic error", provider._OLLAMA_ERROR_MESSAGE),
    ("ollama timeout", provider._OLLAMA_TIMEOUT_MESSAGE),
    ("gemini not set up", provider._GEMINI_NOT_SET_UP_MESSAGE),
]


@pytest.mark.parametrize("label,message", _PROVIDER_MESSAGES, ids=[m[0] for m in _PROVIDER_MESSAGES])
def test_provider_message_states_the_outcome(label, message):
    assert _states_the_outcome(message), f"{label!r} doesn't state whether the email was sent: {message!r}"


def test_provider_messages_are_complete_sentences():
    # A11: no stack traces, no HTTP codes, no snake_case identifiers.
    for _label, message in _PROVIDER_MESSAGES:
        assert message[-1] in ".!?"
        assert "_" not in message
        assert "{" not in message and "}" not in message
