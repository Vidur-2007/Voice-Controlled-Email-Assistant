"""sqlite3 schema, singleton connection, and --seed CLI (§27).

A SINGLETON connection, not a fresh one per call, because `:memory:`
(used by tests/conftest.py) is connection-scoped — a new
sqlite3.connect(":memory:") on every call would silently create a brand
new, empty database each time, making seeded data invisible to
subsequent queries.

Bare @lru_cache is not quite safe here: CPython's lock only guards the
cache dict, not the call to the wrapped function itself, so two threads
racing on the very first call could each construct a connection. Given a
duplicated *connection* (not just a duplicated settings object) would be
a real, if rare, correctness problem for :memory: specifically, this uses
an explicit double-checked lock instead.

Hard rule: nothing may call get_connection() at *module import time* —
that would create the connection before tests/conftest.py's
DB_PATH=":memory:" override takes effect (mirrors the existing "construct
lazily inside functions" engineering rule).
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from backend.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  group_name TEXT DEFAULT '',
  use_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS aliases (
  alias TEXT PRIMARY KEY,
  contact_id INTEGER NOT NULL REFERENCES contacts(id)
);
CREATE TABLE IF NOT EXISTS prefs (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tone_history (
  recipient TEXT PRIMARY KEY,
  tone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS phrases (
  id INTEGER PRIMARY KEY,
  text TEXT NOT NULL,
  use_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scheduled (
  id INTEGER PRIMARY KEY,
  send_at TEXT NOT NULL,
  draft_json TEXT NOT NULL,
  sent INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sent_log (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  recipient TEXT, subject TEXT, tone TEXT
);
"""

SEED_FILE = Path(__file__).parent / "seed_contacts.json"

_lock = threading.Lock()
_connection: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """The one shared connection. check_same_thread=False because
    FastAPI's threadpool runs handlers on different threads.
    """
    global _connection
    if _connection is None:
        with _lock:
            if _connection is None:  # re-check: another thread may have won the race
                settings = get_settings()
                conn = sqlite3.connect(settings.db_path, check_same_thread=False)
                conn.executescript(SCHEMA)
                conn.commit()
                _connection = conn
    return _connection


def reset_connection_for_tests() -> None:
    """Force the next get_connection() to open a fresh connection (and
    thus, under DB_PATH=":memory:", a fresh empty database).
    """
    global _connection
    if _connection is not None:
        try:
            _connection.close()
        except sqlite3.Error:
            pass
    _connection = None


def seed(conn: Optional[sqlite3.Connection] = None, seed_path: Optional[Path] = None) -> None:
    """Load seed_contacts.json into contacts/aliases, replacing whatever
    was there before.
    """
    conn = conn or get_connection()
    path = seed_path or SEED_FILE
    data = json.loads(path.read_text(encoding="utf-8"))

    conn.execute("DELETE FROM aliases")
    conn.execute("DELETE FROM contacts")

    name_to_id: dict[str, int] = {}
    for c in data.get("contacts", []):
        cur = conn.execute(
            "INSERT INTO contacts (name, email, group_name) VALUES (?, ?, ?)",
            (c["name"], c["email"], c.get("group", "")),
        )
        name_to_id[c["name"]] = cur.lastrowid

    for a in data.get("aliases", []):
        contact_id = name_to_id.get(a["contact"])
        if contact_id is not None:
            conn.execute(
                "INSERT OR REPLACE INTO aliases (alias, contact_id) VALUES (?, ?)",
                (a["alias"].strip().lower(), contact_id),
            )

    conn.commit()


if __name__ == "__main__":
    import sys

    if "--seed" in sys.argv:
        seed()
        print("Seeded.")
    else:
        print("Usage: python -m backend.data.store --seed")
