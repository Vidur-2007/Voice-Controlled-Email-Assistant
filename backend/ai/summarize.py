"""Thread summarization (Phase 6, F38) — same fake/real switch pattern as
compose.py/edit.py.
"""

from backend.ai import prompts, provider
from backend.ai.schemas import SummaryFields
from backend.config import get_settings

_FAKE_SENTENCE_LIMIT = 2


def summarize(thread_text: str) -> str:
    settings = get_settings()
    if settings.fake_ai:
        return _fake_summarize(thread_text)
    return _real_summarize(thread_text)


def _fake_summarize(thread_text: str) -> str:
    """Can't fake real insight — same "pass something reasonable through"
    precedent as _fake_revise: the first couple of sentences of the
    thread, which is at least deterministic and exercises the plumbing.
    """
    text = thread_text.strip()
    if not text:
        return "This message doesn't have any readable content."

    sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    summary = ". ".join(sentences[:_FAKE_SENTENCE_LIMIT])
    return (summary + ".") if summary else "This message doesn't have any readable content."


def _real_summarize(thread_text: str) -> str:
    text = thread_text.strip()
    if not text:
        return "This message doesn't have any readable content."

    user = f"Thread text:\n{text}"
    fields = provider.generate(prompts.SYSTEM_SUMMARISE, user, SummaryFields)
    return fields.summary.strip() or "This message doesn't have any readable content."
