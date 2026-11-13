from fastapi.testclient import TestClient

from backend.app.main import app


def test_paid_generation_requires_admin_token(monkeypatch):
    monkeypatch.setenv("NOVUM_ADMIN_TOKEN", "secret-test-token")
    client = TestClient(app)
    data = {"title": "Test", "script": "An abstract server room.", "visual_source": "ai_auto",
            "storyboard_approved": "true", "max_generations": "1"}
    files = {"narration": ("voice.mp3", b"dummy", "audio/mpeg")}
    response = client.post("/api/projects", data=data, files=files)
    assert response.status_code == 403
    assert "administrator token" in response.json()["detail"]


def test_storyboard_preview_is_non_billable():
    client = TestClient(app)
    response = client.post("/api/ai/storyboard", data={
        "title": "Cybersecurity", "script": "An engineer inspects an encrypted server.",
        "visual_source": "hybrid_auto", "stock_max_clips": "1",
    })
    assert response.status_code == 200
    assert len(response.json()["visual_plan"]) == 1
    assert response.json()["timings_are_estimates"]
