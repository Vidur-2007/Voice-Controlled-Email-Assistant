"""Uncertainty heuristics (PHASE_10_PLUS_SPEC.md §11.1, F53) — knowing
WHICH words in a turn might have been misheard.

`SpeechRecognitionAlternative.confidence` was checked directly against a
real microphone (the throwaway `dev_tools/confidence_probe.html` probe)
and found unusable: every interim result reports one of two fixed
constants (0.01 or 0.9) regardless of content, final-result confidence is
reported once per whole utterance (never per word), it clusters too
tightly (0.76-0.89 across ten utterances) to rank individual words, and
it didn't move at all on an utterance that visibly self-corrected
mid-recognition. These heuristics are the chosen replacement, not a
fallback bolted on next to a working signal.
"""

import difflib
import re
from typing import Optional

_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize_words(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def diff_uncertain_words(last_interim: Optional[str], final: str) -> set[str]:
    """Heuristic 1: words the recognizer only settled on at the very end —
    inserted or replaced relative to the last interim result shown before
    finalization. Needs no browser cooperation and is directly observable
    in real data (a word visibly changing between interim and final).
    Empty/`None` interim -> empty set (nothing to compare against, not an
    error).
    """
    if not last_interim:
        return set()
    before = _normalize_words(last_interim)
    after = _normalize_words(final)
    if not after:
        return set()
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    uncertain: set[str] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "insert"):
            uncertain.update(after[j1:j2])
    return uncertain


def is_uncertain_against_contacts(word: str, known_names: set[str]) -> bool:
    """Heuristic 2, deliberately scoped to recipient-hint words ONLY by
    its caller (collect_uncertain_words) — ASR transcripts aren't
    reliably capitalized, so generic proper-noun detection by casing
    would under-fire; checking against a known-names set instead needs no
    capitalization signal at all, but would flag almost every ordinary
    word as "unknown" if run over a whole sentence, which is why this is
    never called on anything but a recipient hint.
    """
    low = word.strip(".,!?").lower()
    if not low:
        return False
    return low.isalpha() and low not in known_names


_ADDRESS_FRAGMENT_RE = re.compile(r"[@._-]")
_NUMBER_OR_DATE_RE = re.compile(r"\d")


def is_address_fragment(word: str) -> bool:
    """Heuristic 3a: a literal email-address-shaped fragment (any token
    containing @/./_/- that survived into the drafted text).
    """
    return bool(_ADDRESS_FRAGMENT_RE.search(word))


def is_number_or_date_fragment(word: str) -> bool:
    """Heuristic 3b: numbers, times, and dates — misheard digits are both
    common and high-cost.
    """
    return bool(_NUMBER_OR_DATE_RE.search(word))


# Heuristic 4: command-word homophones. Not claimed exhaustive (see the
# Phase 11 plan's ambiguity #3) — a starting set, easy to extend from
# real usage.
_HOMOPHONE_PAIRS: list[frozenset] = [
    frozenset({"send", "sent"}),
    frozenset({"to", "two", "too"}),
    frozenset({"for", "four"}),
    frozenset({"write", "right"}),
    frozenset({"their", "there", "they're"}),
    frozenset({"won", "one"}),
]
_HOMOPHONE_WORDS = frozenset(w for pair in _HOMOPHONE_PAIRS for w in pair)


def is_command_homophone(word: str) -> bool:
    return word.strip(".,!?").lower() in _HOMOPHONE_WORDS


def collect_uncertain_words(
    transcript: str,
    last_interim: Optional[str],
    recipient_hint: str,
    known_contact_names: set[str],
) -> set[str]:
    """The one function callers use — combines all four heuristics into a
    single normalized (lowercased, punctuation-stripped) set of words to
    treat as uncertain. `recipient_hint` scopes heuristic 2 to exactly the
    words that were extracted as the spoken recipient name, never the
    whole transcript (see `is_uncertain_against_contacts`'s docstring).
    """
    uncertain: set[str] = set()
    uncertain.update(w.lower() for w in diff_uncertain_words(last_interim, transcript))

    for raw_word in recipient_hint.split():
        word = raw_word.strip(".,!?")
        if word and is_uncertain_against_contacts(word, known_contact_names):
            uncertain.add(word.lower())

    for raw_word in transcript.split():
        word = raw_word.strip(".,!?")
        if not word:
            continue
        if is_address_fragment(word) or is_number_or_date_fragment(word) or is_command_homophone(word):
            uncertain.add(word.lower())

    return uncertain
