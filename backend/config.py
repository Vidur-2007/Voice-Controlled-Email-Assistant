"""Settings — the single source of truth for configuration.

Everything else imports `get_settings()` rather than reading `os.environ`
directly. `load_dotenv()` runs at import time, before any Settings object is
constructed, so a `.env` file in the repo root is always picked up.
"""

from functools import lru_cache

from pydantic import BaseModel
import os
from dotenv import load_dotenv

load_dotenv()  # must run before Settings is constructed


class Settings(BaseModel):
    # --- language model (free, local by default) ---
    llm_provider: str = "ollama"  # "ollama" | "gemini"
    llm_model: str = "llama3.2:3b"
    ollama_host: str = "http://localhost:11434"
    llm_keep_alive: str = "30m"  # keeps the model resident; avoids a slow reload per call
    llm_num_predict: int = 320  # hard cap on generated tokens — latency AND accessibility
    llm_timeout_s: int = 120  # CPU inference is slow; do not set this low
    gemini_api_key: str = ""  # only used if llm_provider == "gemini"
    gemini_model: str = "gemini-2.0-flash"

    fake_ai: bool = True
    fake_gmail: bool = True
    db_path: str = "app.db"
    gmail_credentials_path: str = "credentials.json"
    gmail_token_path: str = "token.json"
    outbox_path: str = "outbox.jsonl"
    silence_stop_ms: int = 0  # 0 = disabled (F10)
    user_first_name: str = ""  # used for sign-offs (F19)
    attachments_dir: str = "attachments"  # F30
    scheduler_poll_s: int = 30  # F35 — how often the background poller checks for due sends
    log_content: bool = False  # F54 — see the privacy rule in PHASE_10_PLUS_SPEC.md §10.2.
    # Default OFF. Only a consented study session should ever set this to 1.


@lru_cache
def get_settings() -> Settings:
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "ollama"),
        llm_model=os.getenv("LLM_MODEL", "llama3.2:3b"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        llm_keep_alive=os.getenv("LLM_KEEP_ALIVE", "30m"),
        llm_num_predict=int(os.getenv("LLM_NUM_PREDICT", "320")),
        llm_timeout_s=int(os.getenv("LLM_TIMEOUT_S", "120")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        fake_ai=os.getenv("FAKE_AI", "1") == "1",
        fake_gmail=os.getenv("FAKE_GMAIL", "1") == "1",
        db_path=os.getenv("DB_PATH", "app.db"),
        gmail_credentials_path=os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json"),
        gmail_token_path=os.getenv("GMAIL_TOKEN_PATH", "token.json"),
        outbox_path=os.getenv("OUTBOX_PATH", "outbox.jsonl"),
        silence_stop_ms=int(os.getenv("SILENCE_STOP_MS", "0")),
        user_first_name=os.getenv("USER_FIRST_NAME", ""),
        attachments_dir=os.getenv("ATTACHMENTS_DIR", "attachments"),
        scheduler_poll_s=int(os.getenv("SCHEDULER_POLL_S", "30")),
        log_content=os.getenv("LOG_CONTENT", "0") == "1",
    )
