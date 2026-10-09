"""backend/uncertainty.py — F53's uncertainty heuristics (§11.1-11.2a).
Pure functions, no FastAPI needed.
"""

from backend.uncertainty import (
    collect_uncertain_words,
    diff_uncertain_words,
    is_address_fragment,
    is_command_homophone,
    is_number_or_date_fragment,
    is_uncertain_against_contacts,
)


def test_diff_uncertain_words_identical_strings_is_empty():
    assert diff_uncertain_words("tell John I will be late", "tell John I will be late") == set()


def test_diff_uncertain_words_one_changed_word():
    # Mirrors the real probe data: "mom ton" (interim) -> "Mom tonight" (final).
    uncertain = diff_uncertain_words("call mom ton", "call mom tonight")
    assert uncertain == {"tonight"}


def test_diff_uncertain_words_none_or_empty_interim_is_empty():
    assert diff_uncertain_words(None, "tell John I will be late") == set()
    assert diff_uncertain_words("", "tell John I will be late") == set()


def test_diff_uncertain_words_empty_final_is_empty():
    assert diff_uncertain_words("tell John", "") == set()


def test_is_uncertain_against_contacts():
    known = {"john", "smith", "sarah", "lee"}
    assert is_uncertain_against_contacts("John", known) is False  # known, case-insensitive
    assert is_uncertain_against_contacts("Zyxlor", known) is True  # unknown
    assert is_uncertain_against_contacts("42", known) is False  # not alphabetic -> not a name at all


def test_is_address_fragment():
    assert is_address_fragment("john.smith@example.com") is True
    assert is_address_fragment("under_score") is True
    assert is_address_fragment("hello") is False


def test_is_number_or_date_fragment():
    assert is_number_or_date_fragment("7:00") is True
    assert is_number_or_date_fragment("tomorrow") is False


def test_is_command_homophone():
    assert is_command_homophone("sent") is True
    assert is_command_homophone("two") is True
    assert is_command_homophone("hello") is False


def test_collect_uncertain_words_combines_heuristics():
    uncertain = collect_uncertain_words(
        transcript="tell Zyxlor I will be there at 7:00 reach me at john.smith@example.com sent",
        last_interim=None,
        recipient_hint="Zyxlor",
        known_contact_names={"john", "smith"},
    )
    assert "zyxlor" in uncertain  # heuristic 2: unknown recipient hint
    assert "7:00" in uncertain  # heuristic 3b: number/time
    assert "john.smith@example.com" in uncertain  # heuristic 3a: address fragment
    assert "sent" in uncertain  # heuristic 4: homophone


def test_collect_uncertain_words_scopes_heuristic_2_to_recipient_hint_only():
    # An ordinary unrecognized word elsewhere in the transcript must NOT
    # be flagged just because it isn't a known contact name — heuristic 2
    # only ever runs against recipient_hint (Phase 11 plan's ambiguity #2).
    # ("meeting"/"late" are plain words with no homophone/address/number
    # collision, so a bare set() here isolates heuristic 2 specifically.)
    uncertain = collect_uncertain_words(
        transcript="tell John I will be late about the meeting",
        last_interim=None,
        recipient_hint="John",
        known_contact_names={"john"},
    )
    assert uncertain == set()


def test_collect_uncertain_words_includes_interim_diff():
    uncertain = collect_uncertain_words(
        transcript="call mom tonight",
        last_interim="call mom ton",
        recipient_hint="",
        known_contact_names=set(),
    )
    assert "tonight" in uncertain
