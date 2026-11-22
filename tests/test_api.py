from fastapi.testclient import TestClient

from copilot import api


def _client() -> TestClient:
    return TestClient(api.app)


def test_healthz_does_not_need_database():
    client = _client()
    assert client.get("/healthz").json() == {"status": "ok"}


def test_metrics_exposes_copilot_counters():
    body = _client().get("/metrics").text
    assert "copilot_incidents_total" in body
    assert "copilot_approvals_total" in body
