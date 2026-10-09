"""F55 — voice inbox search (PHASE_10_PLUS_SPEC.md §13.1). Offline only
(FAKE_AI=1/FAKE_GMAIL=1, conftest.py) — no real Gmail API call, no model
call.
"""

from backend.ai.search_query import parse_search_query
from backend.gmail import fake
from backend.gmail.inbox import search


def test_parse_search_query_extracts_sender():
    fields = parse_search_query("from Priya")
    assert fields.sender == "Priya"
    assert fields.subject_terms == ""


def test_parse_search_query_extracts_topic():
    fields = parse_search_query("about the timetable")
    assert fields.subject_terms == "the timetable"
    assert fields.sender == ""


def test_parse_search_query_extracts_both():
    fields = parse_search_query("from Priya about the invoice")
    assert fields.sender == "Priya"
    assert fields.subject_terms == "the invoice"


def test_parse_search_query_nothing_recognized_is_empty():
    fields = parse_search_query("the quarterly numbers")
    assert fields.sender == ""
    assert fields.subject_terms == ""


def test_fake_search_matches_by_sender():
    fields = parse_search_query("from Priya")
    items = search(fields, limit=10)
    assert len(items) == 1
    assert items[0].sender_name == "Priya Nair"


def test_fake_search_matches_by_subject():
    fields = parse_search_query("about Lunch")
    items = search(fields, limit=10)
    assert len(items) == 1
    assert "Lunch" in items[0].subject


def test_fake_search_no_match_returns_empty():
    fields = parse_search_query("from Zyxlor")
    items = search(fields, limit=10)
    assert items == []


def test_fake_search_excludes_archived(client):
    # Archive David Chen's message via the normal voice flow, then confirm
    # a search for him no longer surfaces it.
    client.post("/api/turn", json={"session_id": "search-archive", "transcript": "read my unread mail"})
    client.post("/api/turn", json={"session_id": "search-archive", "transcript": "next email"})
    client.post("/api/turn", json={"session_id": "search-archive", "transcript": "archive this"})

    fields = parse_search_query("from David")
    items = search(fields, limit=10)
    assert items == []


# ---------------------------------------------------------------------------
# Route-level: results enter reading_inbox, navigation/summarise/reply work
# ---------------------------------------------------------------------------


def test_search_route_level_finds_and_enters_reading_inbox(client):
    resp = client.post(
        "/api/turn", json={"session_id": "search-1", "transcript": "find the email from Priya"}
    )
    body = resp.json()
    assert body["phase"] == "reading_inbox"
    assert "matches" in body["speech"] or "match" in body["speech"]
    assert "Priya Nair" in body["speech"]


def test_search_route_level_no_match(client):
    resp = client.post(
        "/api/turn", json={"session_id": "search-2", "transcript": "search for the message about zyxlorp"}
    )
    body = resp.json()
    assert body["speech"] == "I couldn't find any message matching that. Try naming just the sender."


def test_search_results_support_navigation_and_summarise(client):
    session_id = "search-nav"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "search for the message about project"}
    )
    r = client.post("/api/turn", json={"session_id": session_id, "transcript": "summarise this one"})
    body = r.json()
    assert body["ok"] is True
    assert body["speech"]


def test_search_blocked_mid_draft(client):
    session_id = "search-guard"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    r = client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "find the email from Priya"}
    )
    body = r.json()
    assert body["phase"] == "awaiting_confirm"  # draft untouched
    assert "middle of a message" in body["speech"]
