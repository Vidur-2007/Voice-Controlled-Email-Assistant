"""Offline tests for backend/text_correction.py (F9)."""

from backend.text_correction import strip_correction


def test_no_marker_returns_unchanged():
    assert strip_correction("tell John I will be late") == "tell John I will be late"


def test_marker_in_middle_keeps_text_after():
    result = strip_correction("tell John I'll call at 5, no wait, make that 6")
    assert result == "make that 6"


def test_marker_at_start_keeps_everything_after():
    result = strip_correction("scratch that tell John I'll be late")
    assert result == "tell John I'll be late"


def test_multiple_markers_keeps_only_after_the_last():
    result = strip_correction("tell John I mean tell Sarah no wait tell David I'll be late")
    assert result == "tell David I'll be late"


def test_marker_only_utterance_returns_empty():
    assert strip_correction("scratch that") == ""
    assert strip_correction("  no wait  ") == ""


def test_case_insensitive():
    result = strip_correction("Tell John five, NO WAIT, make that six")
    assert result == "make that six"


def test_sorry_i_mean_matched_whole_not_split_by_i_mean():
    """"sorry i mean" is checked before the shorter "i mean" it contains,
    so the kept remainder never has a stray "sorry" stuck to the front.
    """
    result = strip_correction("tell John five, sorry i mean six")
    assert result == "six"


def test_empty_transcript_returns_empty():
    assert strip_correction("") == ""
