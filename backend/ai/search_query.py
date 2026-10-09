"""F55 — turning a spoken search request into plain, structured fields
(§13.1). The fake/real switch follows the same pattern as compose.py/
mode_detect.py/contacts_nlp.py: FAKE_AI=1 never touches the model.

The model (real path) only ever returns plain text fields, never a raw
query string — backend/gmail/inbox.py::search() is the one place that
turns these fields into an actual provider query, deterministically.
"""

import re

from backend.ai import prompts, provider
from backend.ai.schemas import SearchQueryFields
from backend.config import get_settings

_TOPIC_TRIGGER_RE = re.compile(r"\b(?:about|regarding|re)\b", re.IGNORECASE)
_SENDER_RE = re.compile(r"\bfrom\s+(.+)$", re.IGNORECASE)


def parse_search_query(transcript: str) -> SearchQueryFields:
    settings = get_settings()
    if settings.fake_ai:
        return _fake_parse(transcript)
    return provider.generate(prompts.SYSTEM_SEARCH_QUERY, transcript, SearchQueryFields)


def _fake_parse(transcript: str) -> SearchQueryFields:
    """Deterministic, offline stand-in (§5/the addendum's offline rule) —
    simple keyword extraction only. Date phrases (after/before) are left
    empty in fake mode; faking real date parsing isn't worth the
    complexity for what's already a secondary filter.
    """
    topic_match = _TOPIC_TRIGGER_RE.search(transcript)
    if topic_match:
        before_topic = transcript[: topic_match.start()]
        subject_terms = transcript[topic_match.end() :].strip().rstrip(".,!?")
    else:
        before_topic = transcript
        subject_terms = ""

    sender_match = _SENDER_RE.search(before_topic)
    sender = sender_match.group(1).strip().rstrip(".,!?") if sender_match else ""

    return SearchQueryFields(sender=sender, subject_terms=subject_terms, after="", before="")
