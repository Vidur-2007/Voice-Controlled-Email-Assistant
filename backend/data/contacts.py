"""Contact resolution — deterministic first, model second (§26).

Order: alias -> group -> fuzzy search -> decision rule -> AI escalation
-> deterministic fallback question. Aliases and groups are exact,
case-insensitive lookups against a small controlled vocabulary — never
fuzzy — so they can never collide with name-matching.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional

from rapidfuzz import fuzz, process, utils

from backend.ai.contacts_nlp import resolve as ai_resolve
from backend.data.store import get_connection
from backend.models import ContactCandidate
from backend.speechify import build_disambiguation_question

TOP_CONFIDENT = 90
SECOND_MUST_BE_BELOW = 70
MIN_PLAUSIBLE = 60

_GROUP_STOP_WORDS = ("the", "whole", "entire", "all", "of")

ResolveStatus = Literal["resolved", "clarifying", "unknown", "empty"]


@dataclass
class ResolutionResult:
    status: ResolveStatus
    name: str = ""
    email: str = ""
    candidates: list[ContactCandidate] = field(default_factory=list)
    question: str = ""


def resolve_alias(hint: str) -> Optional[ContactCandidate]:
    """Exact, case-insensitive alias lookup.

    Tries the hint as given first, then — because the real AI path's
    `recipient_hint` extraction sometimes drops the possessive ("my
    manager" -> "manager", observed live against real Ollama) — retries
    with "my "/"our " prefixed, so aliases still resolve even when the
    model normalizes away the word that made it a relationship reference
    in the first place. The fake path never has this problem (its
    heuristic keeps "my"/"our" attached), so this is purely a real-mode
    robustness fix.
    """
    conn = get_connection()
    stripped = hint.strip().lower()
    candidates_to_try = [stripped]
    if stripped and not stripped.startswith(("my ", "our ")):
        candidates_to_try.append(f"my {stripped}")
        candidates_to_try.append(f"our {stripped}")

    for key in candidates_to_try:
        row = conn.execute(
            "SELECT c.name, c.email FROM aliases a JOIN contacts c ON c.id = a.contact_id "
            "WHERE a.alias = ?",
            (key,),
        ).fetchone()
        if row:
            return ContactCandidate(name=row[0], email=row[1], score=100.0)
    return None


def _normalize_group_hint(hint: str) -> str:
    words = [w for w in hint.strip().lower().split() if w not in _GROUP_STOP_WORDS]
    return " ".join(words)


def resolve_group(hint: str) -> list[ContactCandidate]:
    normalized = _normalize_group_hint(hint)
    if not normalized:
        return []
    conn = get_connection()
    rows = conn.execute(
        "SELECT name, email FROM contacts WHERE LOWER(group_name) = ? AND group_name != ''",
        (normalized,),
    ).fetchall()
    return [ContactCandidate(name=r[0], email=r[1], score=100.0) for r in rows]


def search(hint: str) -> list[ContactCandidate]:
    """Fuzzy name search, filtered to plausible matches (score >= 60),
    sorted by score desc then use_count desc (F43 tie-breaking).
    """
    conn = get_connection()
    rows = conn.execute("SELECT name, email, use_count FROM contacts").fetchall()
    if not rows:
        return []

    names = [r[0] for r in rows]
    by_name = {r[0]: r for r in rows}

    # processor=utils.default_process is mandatory, not a style choice —
    # without it, case differences alone tank scores and same-first-name
    # ties become false, non-tied winners (verified empirically).
    matches = process.extract(
        hint, names, scorer=fuzz.WRatio, processor=utils.default_process, limit=5
    )

    scored = []
    for name, score, _idx in matches:
        if score < MIN_PLAUSIBLE:
            continue
        _, email, use_count = by_name[name]
        scored.append((ContactCandidate(name=name, email=email, score=score), use_count))

    scored.sort(key=lambda pair: (-pair[0].score, -pair[1]))
    return [candidate for candidate, _use_count in scored]


def increment_use_count(email: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE contacts SET use_count = use_count + 1 WHERE email = ?", (email,))
    conn.commit()


def _resolve_deterministic(hint: str) -> ResolutionResult:
    """The alias -> group -> fuzzy-with-confidence-rule core, shared by
    `resolve_recipient()` (TO field, adds AI escalation on top for a
    genuinely ambiguous fuzzy result) and `resolve_cc_hint()` (CC/BCC,
    Phase 7 — deliberately does NOT escalate; a "clarifying" result here
    means the caller should just report a flat failure, never open a
    second disambiguation sub-conversation).
    """
    hint = hint.strip()
    if not hint:
        return ResolutionResult(status="empty")

    alias_match = resolve_alias(hint)
    if alias_match:
        increment_use_count(alias_match.email)
        return ResolutionResult(status="resolved", name=alias_match.name, email=alias_match.email)

    group_matches = resolve_group(hint)
    if group_matches:
        for c in group_matches:
            increment_use_count(c.email)
        names = ", ".join(c.name for c in group_matches)
        emails = ", ".join(c.email for c in group_matches)
        return ResolutionResult(status="resolved", name=names, email=emails)

    candidates = search(hint)
    if not candidates:
        return ResolutionResult(status="unknown")

    top = candidates[0]

    # Exactly one plausible candidate: only ever "resolved" (confident) or
    # "unknown" — never "clarifying". There is nothing to disambiguate
    # between with a single option; asking "which one?" with one name
    # would be nonsensical. (A weak single match — e.g. an unrelated name
    # that happens to share some letters — must not masquerade as
    # ambiguity; verified empirically this is a real, not theoretical,
    # case.)
    if len(candidates) == 1:
        if top.score >= TOP_CONFIDENT:
            increment_use_count(top.email)
            return ResolutionResult(status="resolved", name=top.name, email=top.email)
        return ResolutionResult(status="unknown")

    second_score = candidates[1].score
    if top.score >= TOP_CONFIDENT and second_score < SECOND_MUST_BE_BELOW:
        increment_use_count(top.email)
        return ResolutionResult(status="resolved", name=top.name, email=top.email)

    return ResolutionResult(status="clarifying", candidates=candidates)


def resolve_recipient(hint: str, transcript: str) -> ResolutionResult:
    result = _resolve_deterministic(hint)
    if result.status != "clarifying":
        return result

    # Genuinely ambiguous — try the model (real mode; no-ops under
    # FAKE_AI=1), then fall back to a deterministic question.
    candidates = result.candidates
    choice = ai_resolve(hint, candidates, transcript)
    if choice.email:
        matched = next((c for c in candidates if c.email == choice.email), None)
        if matched:
            increment_use_count(matched.email)
            return ResolutionResult(status="resolved", name=matched.name, email=matched.email)

    question = choice.question or build_disambiguation_question(hint, candidates)
    return ResolutionResult(status="clarifying", candidates=candidates, question=question)


def resolve_cc_hint(hint: str) -> ResolutionResult:
    """F29: CC/BCC resolution, deliberately scoped to deterministic-only —
    no AI escalation, no clarifying sub-conversation (which would need to
    distinguish "clarifying the TO" from "clarifying a CC", real, avoidable
    complexity for a non-critical field). An ambiguous hint is reported as
    a flat "unknown" — the caller speaks a failure and asks for a fuller
    name, rather than opening a second disambiguation phase.
    """
    result = _resolve_deterministic(hint)
    if result.status == "clarifying":
        return ResolutionResult(status="unknown")
    return result


_ORDINAL_ANSWERS = {
    "one": 0, "first": 0, "the first": 0, "the first one": 0,
    "two": 1, "second": 1, "the second": 1, "the second one": 1,
    "three": 2, "third": 2, "the third": 2, "the third one": 2,
    "four": 3, "fourth": 3, "the fourth": 3, "the fourth one": 3,
    "five": 4, "fifth": 4, "the fifth": 4, "the fifth one": 4,
}


def match_clarifying_answer(
    transcript: str, candidates: list[ContactCandidate]
) -> Optional[ContactCandidate]:
    """F13: accept an ordinal ('one'/'two'/'the first one') or the
    distinguishing part of a name (e.g. a surname), matched against the
    candidate list stored from the disambiguation question — not a fresh
    fuzzy search.
    """
    low = transcript.strip().lower()

    if low in _ORDINAL_ANSWERS:
        idx = _ORDINAL_ANSWERS[low]
        if idx < len(candidates):
            return candidates[idx]
        return None

    for c in candidates:
        name_low = c.name.lower()
        if low in name_low or name_low in low:
            return c
    return None
