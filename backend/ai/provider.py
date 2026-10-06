"""THE only LLM call site (§19a, §4's engineering rule). No other module
may import an LLM SDK directly — everything funnels through generate(),
which is what makes swapping providers (or adding Gemini) a config change
instead of a rewrite.

Structured output: Ollama constrains generation to a JSON Schema passed in
the `format` parameter, so the Pydantic models in backend/ai/schemas.py
ARE the schema. No tool-use plumbing, no parsing prose.
"""

import logging
import time
from typing import TypeVar

import httpx
from ollama import Client, RequestError, ResponseError
from pydantic import BaseModel, ValidationError

from backend.config import Settings, get_settings
from backend.errors import SpokenError
from backend.events import get_current_session, log_event

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_SCHEMA_RESTATE_TEMPLATE = "\n\nReply with JSON matching this exact schema and nothing else:\n{schema}"

# Phase 8 accessibility audit: these are the messages real users actually
# hear for the §30 "missing model API key"/"model rate limit" rows — every
# real failure path here is wrapped in its own SpokenError before it would
# ever reach errors.py's _PATTERNS table (to_spoken() checks `isinstance(exc,
# SpokenError)` first and returns .message directly), so _PATTERNS' "api
# key"/"rate limit" entries never actually fire in this app as it runs.
# Each message below gained an explicit "so nothing was sent" clause, for
# the same §30-closing-rule reason _PATTERNS' messages did.
_RETRY_FAILED_MESSAGE = "I couldn't write that properly, so nothing was sent. Could you say it again?"
_OLLAMA_NOT_RUNNING_MESSAGE = (
    "I can't write the email right now because Ollama isn't running on this "
    "computer, so nothing was sent. Start Ollama and try again."
)
_OLLAMA_ERROR_MESSAGE = "The writing assistant ran into a problem, so nothing was sent. Say it again in a moment."
_OLLAMA_TIMEOUT_MESSAGE = (
    "That's taking too long to write, so nothing has been sent yet. Say it again, "
    "or try a shorter instruction."
)
_GEMINI_NOT_SET_UP_MESSAGE = (
    "The online writing assistant isn't set up yet, so nothing was sent. Add a "
    "Gemini key to use it, or switch back to the local one."
)


def generate(system: str, user: str, schema_model: type[T]) -> T:
    """The ONLY place an LLM is called. Returns a validated Pydantic object."""
    settings = get_settings()
    if settings.llm_provider == "ollama":
        return _generate_ollama(system, user, schema_model, settings)
    if settings.llm_provider == "gemini":
        return _generate_gemini(system, user, schema_model, settings)
    raise ValueError(f"unknown provider {settings.llm_provider}")


def _call_ollama(system: str, user: str, schema: dict, settings: Settings) -> str:
    """One request to Ollama. Returns raw JSON text, or raises SpokenError."""
    client = Client(host=settings.ollama_host, timeout=settings.llm_timeout_s)
    start = time.monotonic()
    try:
        resp = client.chat(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            format=schema,
            keep_alive=settings.llm_keep_alive,
            options={"num_predict": settings.llm_num_predict, "temperature": 0.4},
        )
    except ConnectionError as exc:
        _log_failure("connection failed", start)
        raise SpokenError(_OLLAMA_NOT_RUNNING_MESSAGE) from exc
    except httpx.TimeoutException as exc:
        _log_failure("timed out", start)
        raise SpokenError(_OLLAMA_TIMEOUT_MESSAGE) from exc
    except (RequestError, ResponseError) as exc:
        _log_failure(f"request/response error: {exc}", start)
        raise SpokenError(_OLLAMA_ERROR_MESSAGE) from exc

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info("provider.generate model=%s elapsed_ms=%.0f", settings.llm_model, elapsed_ms)
    return resp.message.content or ""


def _log_failure(reason: str, start: float) -> None:
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.warning("ollama call failed (%s) elapsed_ms=%.0f", reason, elapsed_ms)


def _generate_ollama(system: str, user: str, schema_model: type[T], settings: Settings) -> T:
    schema = schema_model.model_json_schema()
    start = time.monotonic()
    retried = False

    content = _call_ollama(system, user, schema, settings)
    try:
        result = schema_model.model_validate_json(content)
    except ValidationError:
        logger.warning("schema validation failed on first attempt, retrying once")
        retried = True
        retry_user = user + _SCHEMA_RESTATE_TEMPLATE.format(schema=schema)
        content = _call_ollama(system, retry_user, schema, settings)
        try:
            result = schema_model.model_validate_json(content)
        except ValidationError as exc:
            logger.warning("schema validation failed on retry, giving up")
            raise SpokenError(_RETRY_FAILED_MESSAGE) from exc

    # F54: only when a turn is actually in progress (ai/provider.py has no
    # other way to know a session id — see backend/events.py) — the
    # stateless /api/draft/* endpoints never set this, so a direct call
    # from there logs nothing, by design.
    session_id = get_current_session()
    if session_id is not None:
        log_event(
            session_id,
            "llm_call",
            ms=int((time.monotonic() - start) * 1000),
            detail={
                "fn": schema_model.__name__,
                "model": settings.llm_model,
                "output_words": len(content.split()),
                "retried": retried,
            },
        )
    return result


def _generate_gemini(system: str, user: str, schema_model: type[T], settings: Settings) -> T:
    # Free-tier fallback (§19b). Not configured in this deployment — no
    # GEMINI_API_KEY has been set up and Ollama already works locally, so
    # this is a clearly-labeled stub rather than untested "complete" code.
    # The branch exists so adding a real key later is a config change.
    raise SpokenError(_GEMINI_NOT_SET_UP_MESSAGE)
