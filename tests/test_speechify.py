from datetime import datetime

from backend.models import Draft
from backend.speechify import (
    build_enhanced_readback,
    build_readback,
    normalize_for_speech,
    spell_phonetically,
    speak_schedule_time,
    speak_time_of_day,
    speakable_email,
    word_count,
)


def test_speakable_email_spells_out_address():
    out = speakable_email("john.smith@example.com")
    assert "@" not in out
    assert "." not in out
    assert " at " in out
    assert " dot " in out


def test_normalize_for_speech_strips_markdown():
    out = normalize_for_speech("**Hello** _world_ #tag")
    assert "*" not in out
    assert "_" not in out
    assert "#" not in out


def test_normalize_for_speech_converts_paragraph_breaks_to_pauses():
    out = normalize_for_speech("First paragraph.\n\nSecond paragraph.")
    assert "\n" not in out
    assert "First paragraph." in out
    assert "Second paragraph." in out


def test_normalize_for_speech_spells_out_embedded_email():
    out = normalize_for_speech("Reach me at john@example.com please.")
    assert "@" not in out


def test_word_count():
    assert word_count("one two three") == 3
    assert word_count("") == 0


def test_build_readback_contains_required_sections():
    draft = Draft(recipient_name="John", subject="Running late", body="I will be late.")
    speech = build_readback(draft)
    assert "To John." in speech
    assert "Subject: Running late." in speech
    assert "Message:" in speech
    assert "Say send" in speech


def test_build_readback_uses_speakable_address_when_no_name():
    draft = Draft(recipient="john.smith@example.com", subject="Hi", body="Hello there.")
    speech = build_readback(draft)
    assert "@" not in speech


def test_build_readback_warns_over_120_words():
    long_body = " ".join(["word"] * 150)
    draft = Draft(recipient_name="John", subject="Update", body=long_body)
    speech = build_readback(draft)
    assert "about 150 words" in speech
    assert "Here it is." in speech


def test_build_readback_no_warning_under_120_words():
    short_body = "This is a short message."
    draft = Draft(recipient_name="John", subject="Update", body=short_body)
    speech = build_readback(draft)
    assert "Here it is." not in speech


def test_build_readback_unchanged_when_no_cc_or_attachments():
    draft = Draft(recipient_name="John", subject="Update", body="Hi.")
    speech = build_readback(draft)
    assert "Copying" not in speech
    assert "attachment" not in speech


def test_build_readback_mentions_cc_by_name():
    draft = Draft(
        recipient_name="John",
        subject="Update",
        body="Hi.",
        cc=["sarah.lee@example.com"],
        cc_names=["Sarah Lee"],
    )
    speech = build_readback(draft)
    assert "Copying Sarah Lee." in speech


def test_build_readback_mentions_multiple_cc_with_and():
    draft = Draft(
        recipient_name="John",
        subject="Update",
        body="Hi.",
        cc=["sarah.lee@example.com", "alex.kim@example.com"],
        cc_names=["Sarah Lee", "Alex Kim"],
    )
    speech = build_readback(draft)
    assert "Sarah Lee and Alex Kim" in speech


def test_build_readback_falls_back_to_speakable_address_when_no_cc_name():
    draft = Draft(recipient_name="John", subject="Update", body="Hi.", cc=["sarah.lee@example.com"])
    speech = build_readback(draft)
    assert "sarah dot lee at example dot com" in speech


def test_build_readback_mentions_one_attachment():
    draft = Draft(recipient_name="John", subject="Update", body="Hi.", attachments=["/tmp/x/invoice.pdf"])
    speech = build_readback(draft)
    assert "one attachment: invoice.pdf" in speech


def test_build_readback_mentions_multiple_attachments():
    draft = Draft(
        recipient_name="John",
        subject="Update",
        body="Hi.",
        attachments=["/tmp/x/a.pdf", "/tmp/x/b.png"],
    )
    speech = build_readback(draft)
    assert "2 attachments: a.pdf, b.png" in speech


def test_speak_time_of_day_formats_whole_and_half_hours():
    assert speak_time_of_day(datetime(2026, 1, 1, 17, 0)) == "5 PM"
    assert speak_time_of_day(datetime(2026, 1, 1, 17, 30)) == "5:30 PM"
    assert speak_time_of_day(datetime(2026, 1, 1, 0, 0)) == "12 AM"
    assert speak_time_of_day(datetime(2026, 1, 1, 12, 0)) == "12 PM"


def test_speak_schedule_time_plain_today():
    speech = speak_schedule_time(datetime(2026, 1, 1, 17, 0))
    assert speech == "5 PM today"


def test_speak_schedule_time_explicit_tomorrow():
    speech = speak_schedule_time(datetime(2026, 1, 2, 9, 0), is_tomorrow=True)
    assert speech == "9 AM tomorrow"


def test_speak_schedule_time_rolled_forward_discloses_why():
    speech = speak_schedule_time(datetime(2026, 1, 2, 13, 0), rolled_to_tomorrow=True)
    assert "1 PM tomorrow" in speech
    assert "already passed" in speech


# ---------------------------------------------------------------------------
# Phase 11 (§11.4): build_readback() got zero code changes for this phase —
# these assert the FULL literal string, not just a substring, so a future
# change can't quietly alter text the existing suite's `in` assertions
# wouldn't notice.
# ---------------------------------------------------------------------------


def test_build_readback_exact_strings_unchanged_plain():
    draft = Draft(recipient_name="John", subject="Running late", body="I will be late.")
    assert build_readback(draft) == (
        "To John. Subject: Running late. Message: I will be late. "
        "Say send to send it, or tell me what to change."
    )


def test_build_readback_exact_strings_unchanged_with_cc():
    draft = Draft(
        recipient_name="John",
        subject="Update",
        body="Hi.",
        cc=["sarah.lee@example.com"],
        cc_names=["Sarah Lee"],
    )
    assert build_readback(draft) == (
        "To John. Copying Sarah Lee. Subject: Update. Message: Hi. "
        "Say send to send it, or tell me what to change."
    )


def test_build_readback_exact_strings_unchanged_long_body():
    long_body = " ".join(["word"] * 150)
    draft = Draft(recipient_name="John", subject="Update", body=long_body)
    assert build_readback(draft) == (
        "To John. Subject: Update. Message: The message is about 150 words. "
        f"Here it is. {long_body} Say send to send it, or tell me what to change."
    )


# ---------------------------------------------------------------------------
# F52 — spell_phonetically() (§11.2)
# ---------------------------------------------------------------------------


def test_spell_phonetically_letters():
    assert spell_phonetically("ab") == "A for Alpha, B for Bravo"


def test_spell_phonetically_is_case_insensitive():
    assert spell_phonetically("AB") == spell_phonetically("ab")


def test_spell_phonetically_digits_read_as_digits():
    assert spell_phonetically("5") == "5"
    assert spell_phonetically("a1") == "A for Alpha, 1"


def test_spell_phonetically_punctuation_named():
    assert spell_phonetically(".") == "dot"
    assert spell_phonetically("@") == "at"
    assert spell_phonetically("-") == "hyphen"
    assert spell_phonetically("_") == "underscore"


def test_spell_phonetically_full_address():
    out = spell_phonetically("jo@a.io")
    assert out == (
        "J for Juliet, O for Oscar, at, A for Alpha, dot, I for India, O for Oscar"
    )


# ---------------------------------------------------------------------------
# F53 — build_enhanced_readback() (§11.3)
# ---------------------------------------------------------------------------


def test_build_enhanced_readback_zero_uncertain_matches_plain_readback():
    draft = Draft(recipient_name="John", subject="Update", body="Hi.")
    segments = build_enhanced_readback(draft, uncertain_words=set(), spell_recipient=False)
    assert len(segments) == 1
    assert segments[0].text == build_readback(draft)
    assert segments[0].rate == "normal"
    assert segments[0].cue is False


def test_build_enhanced_readback_never_announces_zero_uncertain_words():
    draft = Draft(recipient_name="John", subject="Update", body="Hi there friend.")
    segments = build_enhanced_readback(draft, uncertain_words={"nonexistentword"}, spell_recipient=False)
    full_text = " ".join(s.text for s in segments)
    assert "I was unsure about 0" not in full_text
    assert not any(s.cue for s in segments)


def test_build_enhanced_readback_marks_exactly_the_uncertain_word():
    draft = Draft(recipient_name="John", subject="Update", body="Call mom tonight please.")
    segments = build_enhanced_readback(draft, uncertain_words={"tonight"}, spell_recipient=False)
    cued = [s for s in segments if s.cue]
    assert len(cued) == 1
    assert cued[0].text.strip(".,") == "tonight"
    assert cued[0].rate == "slow"
    full_text = " ".join(s.text for s in segments)
    assert "I was unsure about 1 word." in full_text


def test_build_enhanced_readback_multiple_uncertain_words_use_plural():
    draft = Draft(recipient_name="John", subject="Update", body="Call mom tonight please.")
    segments = build_enhanced_readback(draft, uncertain_words={"tonight", "please"}, spell_recipient=False)
    full_text = " ".join(s.text for s in segments)
    assert "I was unsure about 2 words." in full_text


def test_build_enhanced_readback_auto_spells_unfamiliar_recipient_even_with_nothing_uncertain():
    draft = Draft(recipient="unknown.name@example.com", recipient_name="Unknown Name", subject="Hi", body="Hi.")
    segments = build_enhanced_readback(draft, uncertain_words=set(), spell_recipient=True)
    full_text = " ".join(s.text for s in segments)
    assert "U for Uniform" in full_text  # spelled form of the address present
    assert "I was unsure about 0" not in full_text  # spelling != uncertainty
