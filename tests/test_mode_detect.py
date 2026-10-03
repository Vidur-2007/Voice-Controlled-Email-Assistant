"""Offline tests for backend/ai/mode_detect.py — word-count heuristics,
explicit override phrases (F4), and F5's answer matching. FAKE_AI=1
throughout (conftest.py), so the ambiguous 15-40 word zone never calls a
model here.
"""

from backend.ai.mode_detect import check_override, detect_mode, match_mode_answer


def test_short_transcript_is_brief_no_ask():
    result = detect_mode("tell john I will be late")  # 6 words
    assert result.ask is False
    assert result.mode == "brief"


def test_long_transcript_is_dictation_no_ask():
    long_transcript = " ".join(["word"] * 45)  # 45 > 40
    result = detect_mode(long_transcript)
    assert result.ask is False
    assert result.mode == "dictation"


def test_ambiguous_zone_defaults_to_brief_under_fake_ai():
    # 20 words: inside the 15-40 "ask the model" zone, but FAKE_AI=1 means
    # there's no fake model to consult — defaults to brief without asking,
    # so the offline flow always stays a single round trip.
    transcript = " ".join(["word"] * 20)
    result = detect_mode(transcript)
    assert result.ask is False
    assert result.mode == "brief"


def test_dictation_override_standalone():
    assert check_override("dictate this") == ("dictation", "")


def test_dictation_override_with_content():
    result = check_override("dictate this I will be late for the meeting")
    assert result == ("dictation", "I will be late for the meeting")


def test_brief_override_standalone():
    assert check_override("write it for me") == ("brief", "")


def test_brief_override_with_content():
    result = check_override("write it for me tell my manager I will be late")
    assert result == ("brief", "tell my manager I will be late")


def test_no_override_returns_none():
    assert check_override("tell john I will be late") is None


def test_match_mode_answer_dictation():
    assert match_mode_answer("dictate it") == "dictation"
    assert match_mode_answer("word for word") == "dictation"


def test_match_mode_answer_brief():
    assert match_mode_answer("write it for me") == "brief"
    assert match_mode_answer("you write it") == "brief"


def test_match_mode_answer_unrecognized_returns_none():
    assert match_mode_answer("banana") is None
