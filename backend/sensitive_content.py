"""F51 (Phase 14, optional) — detecting sensitive content for the spoken-
PIN speed bump before sending.

This is NOT authentication — a PIN spoken aloud is audible to anyone in
the room, which is precisely the threat model it appears to address.
README.md says so plainly; nothing in this module should be read as
implying real security.
"""

import re
from typing import Optional

_KEYWORD_MARKERS = ("password", "otp")
# A loosely-formatted run of 7+ digits — covers both a bare account
# number and a card-like number with spaces or hyphens
# ("4111 1111 1111 1111", "4111-1111-1111-1111").
_DIGIT_RUN_RE = re.compile(r"(?:\d[ -]?){6,}\d")

_DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_TOKEN_RE = re.compile(r"[a-zA-Z]+|\d+")


def contains_sensitive_markers(text: str) -> bool:
    """F51's trigger condition (§14): account numbers, "password", "OTP",
    or a card-like run of digits. Deterministic and narrow by design — a
    missed marker just means no PIN is asked for, never a false sense of
    security.
    """
    low = text.lower()
    if any(keyword in low for keyword in _KEYWORD_MARKERS):
        return True
    return bool(_DIGIT_RUN_RE.search(text))


def parse_spoken_pin(transcript: str) -> Optional[str]:
    """Accepts literal digits ("1234"), spoken digit words ("one two
    three four"), or a mix. Returns a 4-character digit string, or None
    if the transcript doesn't resolve to exactly 4 digits — a wrong
    length is never guessed at or truncated to fit.
    """
    digits: list[str] = []
    for token in _TOKEN_RE.findall(transcript):
        if token.isdigit():
            digits.extend(token)
        else:
            word = token.lower()
            if word in _DIGIT_WORDS:
                digits.append(_DIGIT_WORDS[word])
    pin = "".join(digits)
    return pin if len(pin) == 4 else None
