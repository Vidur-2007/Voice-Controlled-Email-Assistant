"""Structured-output JSON schemas (§19a). These Pydantic models ARE the
schema passed to Ollama's `format=` parameter — no tool-use plumbing, no
parsing prose.
"""

from typing import Literal

from pydantic import BaseModel

from backend.models import Tone


class DraftFields(BaseModel):
    recipient_hint: str  # person named, as spoken; "" if none
    subject: str  # under 60 characters
    body: str  # plain prose, no markdown, no placeholders
    tone: Tone


class ModeChoice(BaseModel):
    mode: Literal["dictation", "brief", "unclear"]
    confidence: float


class ContactChoice(BaseModel):
    email: str  # chosen candidate's email; "" if still ambiguous
    question: str  # spoken disambiguating question; "" if email is set


class SummaryFields(BaseModel):
    summary: str  # a couple of spoken sentences, not the whole thread
