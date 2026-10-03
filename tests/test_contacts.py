"""Tests for backend/data/contacts.py — fuzzy search, aliases, groups, and
the full resolve_recipient() decision flow (§26). FAKE_AI=1 (global
conftest), so ambiguous cases always fall through to the deterministic
disambiguation-question builder, never a real model call.
"""

from backend.data.contacts import resolve_cc_hint, resolve_recipient


def test_bare_john_triggers_clarification():
    result = resolve_recipient("John", "email John")
    assert result.status == "clarifying"
    names = {c.name for c in result.candidates}
    assert names == {"John Smith", "John Carter"}
    assert "Smith" in result.question
    assert "Carter" in result.question
    assert "one" in result.question.lower()
    assert "two" in result.question.lower()


def test_john_smith_resolves_outright():
    result = resolve_recipient("John Smith", "email John Smith")
    assert result.status == "resolved"
    assert result.name == "John Smith"
    assert result.email == "john.smith@example.com"


def test_my_manager_resolves_via_alias():
    result = resolve_recipient("my manager", "tell my manager I will be late")
    assert result.status == "resolved"
    assert result.name == "Sarah Lee"
    assert result.email == "sarah.lee@example.com"


def test_my_supervisor_also_resolves_via_alias():
    result = resolve_recipient("my supervisor", "email my supervisor")
    assert result.status == "resolved"
    assert result.name == "Sarah Lee"


def test_the_team_expands_to_group():
    result = resolve_recipient("the team", "email the team")
    assert result.status == "resolved"
    assert "Sarah Lee" in result.name
    assert "Alex Kim" in result.name
    assert "David Chen" in result.name
    assert "sarah.lee@example.com" in result.email
    assert "alex.kim@example.com" in result.email
    assert "david.chen@example.com" in result.email


def test_the_whole_team_also_expands_to_group():
    result = resolve_recipient("the whole team", "email the whole team")
    assert result.status == "resolved"
    assert "Sarah Lee" in result.name


def test_surname_alone_resolves_unambiguously():
    result = resolve_recipient("Smith", "email Smith")
    assert result.status == "resolved"
    assert result.name == "John Smith"


def test_unknown_contact_returns_unknown_status():
    result = resolve_recipient("Zorblax", "email Zorblax")
    assert result.status == "unknown"


def test_empty_hint_returns_empty_status():
    result = resolve_recipient("", "I need help with the report")
    assert result.status == "empty"


def test_clarifying_answer_by_ordinal(client):
    session_id = "contact-ordinal"
    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "email John about the budget"}
    )
    b1 = r1.json()
    assert b1["phase"] == "clarifying"
    assert "Smith" in b1["speech"]
    assert "Carter" in b1["speech"]

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "two"})
    b2 = r2.json()
    assert b2["phase"] == "awaiting_confirm"
    assert b2["draft"]["recipient_name"] == "John Carter"


def test_clarifying_answer_by_surname(client):
    session_id = "contact-surname"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "email John about the budget"}
    )
    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "Smith"})
    b2 = r2.json()
    assert b2["phase"] == "awaiting_confirm"
    assert b2["draft"]["recipient_name"] == "John Smith"


def test_clarifying_reasks_cleanly_on_two_consecutive_mismatches(client):
    """Regression test for the compounding-prefix bug: reusing the
    previous spoken sentence for the retry would grow "Sorry, I didn't
    catch that." without bound on a second consecutive mismatch.
    """
    session_id = "contact-mismatch"
    client.post("/api/turn", json={"session_id": session_id, "transcript": "email John"})

    r1 = client.post("/api/turn", json={"session_id": session_id, "transcript": "banana"})
    b1 = r1.json()
    assert b1["phase"] == "clarifying"
    assert b1["speech"].count("Sorry, I didn't catch that.") == 1

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "banana"})
    b2 = r2.json()
    assert b2["phase"] == "clarifying"
    assert b2["speech"].count("Sorry, I didn't catch that.") == 1
    assert "Smith" in b2["speech"]
    assert "Carter" in b2["speech"]

    r3 = client.post("/api/turn", json={"session_id": session_id, "transcript": "Carter"})
    b3 = r3.json()
    assert b3["phase"] == "awaiting_confirm"
    assert b3["draft"]["recipient_name"] == "John Carter"


def test_unknown_contact_still_reaches_awaiting_confirm_via_fallback(client):
    """F16: an unrecognized name still lets the user move on via the
    existing permissive awaiting_address fallback.
    """
    session_id = "contact-unknown"
    r1 = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "email Zorblax about the plan"}
    )
    b1 = r1.json()
    assert b1["phase"] == "awaiting_address"
    assert "Zorblax" in b1["speech"]

    r2 = client.post("/api/turn", json={"session_id": session_id, "transcript": "Zorblax"})
    b2 = r2.json()
    assert b2["phase"] == "awaiting_confirm"


# ---------------------------------------------------------------------------
# resolve_cc_hint (F29) — deterministic-only: an ambiguous hint is a flat
# "unknown", never "clarifying" (see the function's own docstring for why).
# ---------------------------------------------------------------------------


def test_cc_hint_alias_resolves():
    result = resolve_cc_hint("my manager")
    assert result.status == "resolved"
    assert result.name == "Sarah Lee"
    assert result.email == "sarah.lee@example.com"


def test_cc_hint_group_resolves_to_multiple():
    result = resolve_cc_hint("the team")
    assert result.status == "resolved"
    assert "Sarah Lee" in result.name
    assert "Alex Kim" in result.name


def test_cc_hint_single_confident_match_resolves():
    result = resolve_cc_hint("Smith")
    assert result.status == "resolved"
    assert result.name == "John Smith"


def test_cc_hint_ambiguous_name_returns_unknown_not_clarifying():
    result = resolve_cc_hint("John")
    assert result.status == "unknown"


def test_cc_hint_unknown_name_returns_unknown():
    result = resolve_cc_hint("Zorblax")
    assert result.status == "unknown"


def test_cc_hint_empty_returns_empty():
    result = resolve_cc_hint("")
    assert result.status == "empty"
