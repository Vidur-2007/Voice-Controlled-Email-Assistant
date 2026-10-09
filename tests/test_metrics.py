"""F54 derived-metrics endpoints (PHASE_10_PLUS_SPEC.md §10.2):
GET /api/metrics/summary and GET /api/metrics/export.csv.
"""

from backend.config import get_settings


def test_metrics_summary_on_empty_database(client):
    resp = client.get("/api/metrics/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["sessions"] == []
    assert body["aggregate"]["turns_per_send"] is None
    assert body["aggregate"]["repair_turns_per_send"] is None
    assert body["aggregate"]["wall_clock_seconds_avg"] is None
    assert body["aggregate"]["model_latency_ms"] == {}
    assert body["aggregate"]["edits_after_readback"] == 0
    assert body["aggregate"]["sends_abandoned"] == 0
    assert body["aggregate"]["readbacks_by_condition"] == {"plain": 0, "enhanced": 0}


def test_metrics_export_csv_on_empty_database(client):
    resp = client.get("/api/metrics/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines == ["id,session_id,ts,event,phase,ms,detail"]


def test_metrics_summary_after_a_real_conversation(client):
    session_id = "metrics-1"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    client.post("/api/turn", json={"session_id": session_id, "transcript": "send"})

    resp = client.get("/api/metrics/summary")
    body = resp.json()
    session_rows = [s for s in body["sessions"] if s["session_id"] == session_id]
    assert len(session_rows) == 1
    assert session_rows[0]["sent"] is True
    assert session_rows[0]["turns"] >= 2
    assert body["aggregate"]["turns_per_send"] is not None


def test_metrics_export_csv_after_a_real_conversation(client):
    session_id = "metrics-2"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    resp = client.get("/api/metrics/export.csv")
    assert session_id in resp.text
    assert "turn_start" in resp.text


def test_metrics_summary_counts_abandoned_send(client):
    session_id = "metrics-abandon"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    client.post("/api/turn", json={"session_id": session_id, "transcript": "cancel"})

    resp = client.get("/api/metrics/summary")
    body = resp.json()
    assert body["aggregate"]["sends_abandoned"] >= 1


def test_metrics_summary_splits_readbacks_by_condition(client, monkeypatch):
    session_id = "metrics-condition"
    client.post(
        "/api/turn", json={"session_id": session_id, "transcript": "tell John Smith I will be late"}
    )
    plain_body = client.get("/api/metrics/summary").json()
    assert plain_body["aggregate"]["readbacks_by_condition"]["plain"] >= 1

    monkeypatch.setenv("ENHANCED_READBACK", "1")
    get_settings.cache_clear()
    try:
        client.post(
            "/api/turn",
            json={"session_id": "metrics-condition-2", "transcript": "tell John Smith I will be late"},
        )
        enhanced_body = client.get("/api/metrics/summary").json()
        assert enhanced_body["aggregate"]["readbacks_by_condition"]["enhanced"] >= 1
    finally:
        monkeypatch.delenv("ENHANCED_READBACK", raising=False)
        get_settings.cache_clear()
