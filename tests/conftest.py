"""Pytest configuration.

The env flags MUST be set, and the settings cache cleared, before anything
imports `backend` — backend.config calls load_dotenv() at import time and
get_settings() is @lru_cache'd, so importing it first would freeze whatever
settings happened to be in the real environment and tests could silently
try to reach real APIs.
"""

import json
import os
import shutil

os.environ["FAKE_AI"] = "1"
os.environ["FAKE_GMAIL"] = "1"
os.environ["DB_PATH"] = ":memory:"
os.environ["OUTBOX_PATH"] = "test_outbox.jsonl"
os.environ["ATTACHMENTS_DIR"] = "test_attachments"

from backend.config import get_settings  # noqa: E402  (must follow the env vars above)

get_settings.cache_clear()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.attachments import reset_attachments_for_tests  # noqa: E402
from backend.data import store  # noqa: E402
from backend.gmail.fake import reset_fake_inbox_for_tests  # noqa: E402
from backend.main import app  # noqa: E402
from backend.session import _sessions  # noqa: E402


def read_outbox_lines() -> list[dict]:
    """Read every line currently in the (test) outbox as parsed JSON."""
    path = get_settings().outbox_path
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _clear_outbox() -> None:
    path = get_settings().outbox_path
    if os.path.exists(path):
        os.remove(path)


def _clear_attachments() -> None:
    path = get_settings().attachments_dir
    if os.path.exists(path):
        shutil.rmtree(path)


def _reseed_contacts() -> None:
    # Forces a fresh :memory: database (connection-scoped) and reloads the
    # fixed seed data — cheap, and simplest since most compose-flow tests
    # now indirectly depend on contacts resolution (e.g. "John Smith").
    store.reset_connection_for_tests()
    store.seed()


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset in-memory sessions, the contacts DB, the fake inbox, the
    test outbox, and test attachments before and after every test.
    """
    _sessions.clear()
    _clear_outbox()
    _clear_attachments()
    _reseed_contacts()
    reset_fake_inbox_for_tests()
    reset_attachments_for_tests()
    yield
    _sessions.clear()
    _clear_outbox()
    _clear_attachments()
    _reseed_contacts()
    reset_fake_inbox_for_tests()
    reset_attachments_for_tests()


@pytest.fixture
def client():
    return TestClient(app)
