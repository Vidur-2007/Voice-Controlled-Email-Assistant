"""F13 — ask the model to pick among ambiguous candidates using the whole
transcript for context, or produce a spoken disambiguating question.

Follows the same fake/real switch pattern as compose.py/edit.py/
mode_detect.py: under FAKE_AI=1 this always no-ops (empty choice), so the
caller falls back to a deterministic question-builder — contacts_nlp
never runs a real model call in fake mode.
"""

from backend.ai import prompts, provider
from backend.ai.schemas import ContactChoice
from backend.config import get_settings
from backend.models import ContactCandidate

_EMPTY_CHOICE = ContactChoice(email="", question="")


def resolve(hint: str, candidates: list[ContactCandidate], transcript: str) -> ContactChoice:
    settings = get_settings()
    if settings.fake_ai:
        return _EMPTY_CHOICE

    candidate_lines = "\n".join(f"- {c.name} <{c.email}>" for c in candidates)
    user = (
        f"The user said: {transcript!r}\n"
        f"They referred to the recipient as: {hint!r}\n"
        f"Candidates:\n{candidate_lines}"
    )
    return provider.generate(prompts.SYSTEM_PICK_CONTACT, user, ContactChoice)
