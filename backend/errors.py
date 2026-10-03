"""Exception -> speech mapping (rule A5 / A11).

Every failure the app can hit becomes a complete, plain English sentence —
never a stack trace, HTTP code, or raw JSON. `SpokenError` is for code that
already knows exactly what should be said; `to_spoken()` is the catch-all
for anything else, including exceptions raised by libraries this app calls.
"""


class SpokenError(Exception):
    """An error that already carries its own spoken-safe message."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


_CATCH_ALL = (
    "Something went wrong and nothing was sent. Your draft is safe. "
    "Say 'help' to hear what you can do."
)

# Condition -> spoken sentence, checked in order against str(exc).lower().
_PATTERNS: list[tuple[str, str]] = [
    ("credentials.json", "I can't send mail yet because the email credentials file is missing."),
    ("credentials_path", "I can't send mail yet because the email credentials file is missing."),
    ("token expired", "My access to your email has expired. Say 'reconnect my email' to sign in again."),
    ("invalid_grant", "My access to your email has expired. Say 'reconnect my email' to sign in again."),
    ("401", "Your email account refused the request. It may not have granted permission to send mail."),
    ("403", "Your email account refused the request. It may not have granted permission to send mail."),
    ("forbidden", "Your email account refused the request. It may not have granted permission to send mail."),
    ("unauthorized", "Your email account refused the request. It may not have granted permission to send mail."),
    ("429", "Your email provider is busy right now. Say 'send' once more to try again."),
    ("500", "Your email provider is busy right now. Say 'send' once more to try again."),
    ("502", "Your email provider is busy right now. Say 'send' once more to try again."),
    ("503", "Your email provider is busy right now. Say 'send' once more to try again."),
    ("invalid recipient", "That address doesn't look right, so I haven't sent it. Say 'change recipient' to fix it."),
    ("invalid address", "That address doesn't look right, so I haven't sent it. Say 'change recipient' to fix it."),
    ("api key", "I can't write the email because the writing assistant isn't set up."),
    ("api_key", "I can't write the email because the writing assistant isn't set up."),
    ("rate limit", "The writing assistant is busy. Say 'try again' in a moment."),
    ("network", "I couldn't reach the internet, so nothing was sent. Your draft is safe."),
    ("connection", "I couldn't reach the internet, so nothing was sent. Your draft is safe."),
]


_NETWORK_DOWN = "I couldn't reach the internet, so nothing was sent. Your draft is safe."

# Real "no internet" failures usually say nothing about "network" or
# "connection" in their text (e.g. httplib2's "Unable to find the server
# at ..."), so match by type, not just by message. Names are compared as
# strings so this module never has to import httplib2/requests itself.
_NETWORK_EXCEPTION_NAMES = {
    "ServerNotFoundError",  # httplib2 (google-api-python-client)
    "gaierror",  # DNS lookup failed
    "ConnectTimeout",
    "ReadTimeout",
    "TransportError",  # google.auth
}


def _is_network_failure(exc: Exception) -> bool:
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    return any(cls.__name__ in _NETWORK_EXCEPTION_NAMES for cls in type(exc).__mro__)


def to_spoken(exc: Exception) -> str:
    """Map any exception to a complete, speakable English sentence."""
    if isinstance(exc, SpokenError):
        return exc.message

    if _is_network_failure(exc):
        return _NETWORK_DOWN

    text = str(exc).lower()
    for needle, sentence in _PATTERNS:
        if needle in text:
            return sentence

    return _CATCH_ALL
