"""Offline tests for /api/draft/compose and /api/draft/edit (§21) — direct
access to compose/edit without the frontend/session machinery. These were
still the Phase-0 stub (zero routes) despite Phases 0-9 being claimed
complete; this is the completeness-pass fix.
"""


def test_draft_compose_with_explicit_mode(client):
    resp = client.post(
        "/api/draft/compose", json={"transcript": "tell John Smith I will be late", "mode": "brief"}
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["body"]
    assert body["subject"]
    # Recipient resolution is deliberately out of scope for this stateless
    # endpoint — no session, no clarifying sub-conversation to have.
    assert body["recipient"] == ""


def test_draft_compose_mode_omitted_defaults_to_brief(client):
    # Under 15 words -> detect_mode() itself would resolve to "brief"
    # without even reaching the ask=True branch; this confirms the
    # omitted-mode path reaches compose_email() at all and produces a
    # normal Draft, without needing to force the ambiguous zone.
    resp = client.post("/api/draft/compose", json={"transcript": "tell Sarah Lee the report is ready"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["body"]


def test_draft_compose_dictation_mode_is_close_to_verbatim(client):
    resp = client.post(
        "/api/draft/compose",
        json={"transcript": "I will be there at five", "mode": "dictation"},
    )
    body = resp.json()
    assert resp.status_code == 200
    assert "five" in body["body"].lower()


def test_draft_edit_applies_instruction(client):
    draft = {
        "recipient": "john@example.com",
        "recipient_name": "John",
        "subject": "Hi",
        "body": "I will be late.",
        "tone": "neutral",
        "length": "normal",
    }
    resp = client.post(
        "/api/draft/edit", json={"draft": draft, "instruction": "make it more formal"}
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["tone"] == "formal"
    assert body["recipient"] == "john@example.com"  # untouched by the edit


def test_draft_edit_free_form_instruction_under_fake_ai_is_a_safe_noop(client):
    # _fake_revise() can't fake real semantic rewriting for an instruction
    # it doesn't recognize — confirms it returns the draft unchanged
    # rather than erroring, same contract revise() already has elsewhere.
    draft = {
        "recipient": "john@example.com",
        "subject": "Hi",
        "body": "I will be late.",
    }
    resp = client.post(
        "/api/draft/edit", json={"draft": draft, "instruction": "remove the last sentence"}
    )
    body = resp.json()
    assert resp.status_code == 200
    assert body["body"] == "I will be late."
