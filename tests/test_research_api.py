"""Research UI authority stays inside the existing loopback operator boundary."""
from fastapi.testclient import TestClient

from gtm.api import create_app
from gtm.research import ResearchDesk
from test_research import context, run


def test_research_review_same_origin_closed_envelope(ready):
    engine, destination, client, worker, action = ready
    desk = ResearchDesk(engine)
    desk.save_run(run(context()))
    with TestClient(create_app(engine, destination, worker)) as browser:
        response = browser.post("/api/research/review", json={})
        assert response.status_code == 403
        response = browser.post("/api/research/review", json={}, headers={"X-Demo-Intent": "operator"})
        assert response.status_code == 409 and response.json()["error"] == "closed_research_review_envelope"
        response = browser.post("/api/research/review", json={}, headers={"X-Demo-Intent": "operator", "Origin": "https://evil.example"})
        assert response.status_code == 403
        response = browser.get("/assets/research.js")
        assert response.status_code == 200 and "default-src 'self'" in response.headers["content-security-policy"]


def test_browser_cannot_supply_a_fake_model_response(ready):
    engine, destination, client, worker, action = ready
    with TestClient(create_app(engine, destination, worker)) as browser:
        response = browser.post("/api/research/infer", json={"model_response": "fabricated"}, headers={"X-Demo-Intent": "operator"})
        assert response.status_code == 404
        response = browser.get("/api/research", headers={"Host": "external.example"})
        assert response.status_code == 403
