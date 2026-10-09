"""Personalisation storage (F42, F44, F45) — three tables that have existed,
unused, since Phase 0 (§27's schema): the generic `prefs` key-value table
(F45, speech rate), `tone_history` (F42, tone per recipient), and `phrases`
(F44, frequent sign-offs/openers — bookkeeping only; nothing in this app
automatically feeds a stored phrase back into a generated email, by
deliberate choice).

Same lazy-`get_connection()`-inside-each-function style as
`backend/data/contacts.py` — never construct/query at import time.
"""

from typing import Optional

from backend.data.store import get_connection

_PHRASE_MAX_LENGTH = 60  # a one-line sign-off/opener, not a whole paragraph


def get_pref(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_connection()
    row = conn.execute("SELECT value FROM prefs WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_pref(key: str, value: str) -> None:
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO prefs (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def get_tone_for_recipient(email: str) -> Optional[str]:
    """F42: "default to it next time." Keyed by email (a stable identity),
    not display name. Returns None if this recipient has never had an
    email successfully sent to them yet.
    """
    email = email.strip().lower()
    if not email:
        return None
    conn = get_connection()
    row = conn.execute("SELECT tone FROM tone_history WHERE recipient = ?", (email,)).fetchone()
    return row[0] if row else None


def set_tone_for_recipient(email: str, tone: str) -> None:
    """F42: "store the chosen tone." Called on SEND success — see this
    module's docstring and the Phase 8 plan for why SEND (not every
    intermediate tone-command during drafting) is "chosen."
    """
    email = email.strip().lower()
    if not email:
        return
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO tone_history (recipient, tone) VALUES (?, ?)", (email, tone))
    conn.commit()


def record_phrase(text: str) -> None:
    """F44: upsert a sign-off/opener's use count. Silently skips empty text
    or anything longer than a one-line phrase (a whole multi-sentence body
    accidentally passed in here would otherwise pollute the table).
    """
    text = text.strip()
    if not text or len(text) > _PHRASE_MAX_LENGTH:
        return
    conn = get_connection()
    row = conn.execute("SELECT id FROM phrases WHERE text = ?", (text,)).fetchone()
    if row:
        conn.execute("UPDATE phrases SET use_count = use_count + 1 WHERE id = ?", (row[0],))
    else:
        conn.execute("INSERT INTO phrases (text, use_count) VALUES (?, 1)", (text,))
    conn.commit()


def top_phrases(limit: int = 5) -> list[tuple[str, int]]:
    """F44: bookkeeping only — nothing in this app calls this to feed a
    phrase back into a generated email (see module docstring). Exposed for
    a future voice command (e.g. "use my usual sign-off") to build on.
    """
    conn = get_connection()
    rows = conn.execute(
        "SELECT text, use_count FROM phrases ORDER BY use_count DESC, text ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def record_signoff_phrase(text: str) -> None:
    """F58 (Phase 13) — a SEPARATE table from `phrases`/`record_phrase()`
    above: that one mixes openers and signoffs together as generic F44
    bookkeeping, which would let an opener that happens to repeat more
    often win "most-used" here. Same upsert shape, same length guard.
    """
    text = text.strip()
    if not text or len(text) > _PHRASE_MAX_LENGTH:
        return
    conn = get_connection()
    row = conn.execute("SELECT id FROM signoff_phrases WHERE text = ?", (text,)).fetchone()
    if row:
        conn.execute("UPDATE signoff_phrases SET use_count = use_count + 1 WHERE id = ?", (row[0],))
    else:
        conn.execute("INSERT INTO signoff_phrases (text, use_count) VALUES (?, 1)", (text,))
    conn.commit()


def top_signoff_phrase() -> Optional[str]:
    """F58 — the single most-used recorded sign-off, or None if nothing
    has been recorded yet.
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT text FROM signoff_phrases ORDER BY use_count DESC, text ASC LIMIT 1"
    ).fetchone()
    return row[0] if row else None
