from types import SimpleNamespace

import pytest

from backend.app.services.scene_director import make_plan, needs_authentic_source, serialized
from backend.app.services import ai_video


def scene(index, text):
    return SimpleNamespace(index=index, text=text, start=index * 5, end=(index + 1) * 5, duration=5)


def test_specific_prompts_no_repeated_generic_search():
    plans = make_plan([scene(0, "A rocket launches from the pad."),
                       scene(1, "An engineer examines a server chip.")], "Space and AI")
    assert plans[0].search_query != plans[1].search_query
    assert plans[0].camera != plans[1].camera
    assert "AI-generated illustration" in serialized(plans)[0]["synthetic_label"]


def test_hybrid_requires_authentic_for_actual_events():
    plans = make_plan([scene(0, "The company announced an outage today."),
                       scene(1, "An abstract data center visualization.")], "Technology")
    assert plans[0].visual_type == "authentic"
    assert plans[1].visual_type == "ai"
    assert needs_authentic_source("The event happened in 2026")


def test_runway_generation_api_is_mockable(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_video, "_request", lambda path, payload=None: (calls.append((path, payload)) or {"id": "task123"}))
    assert ai_video.create_task("Moving clouds", portrait=True) == "task123"
    assert calls[0][0] == "/text_to_video"
    assert calls[0][1]["ratio"] == "720:1280"
    assert ai_video.create_task("Move camera", portrait=False, image_uri="https://example.org/img.jpg") == "task123"
    assert calls[1][0] == "/image_to_video"


def test_runway_rejects_untrusted_image(monkeypatch):
    with pytest.raises(ai_video.AIVideoError):
        ai_video.create_task("test", portrait=True, image_uri="file:///secrets")


def test_runway_task_wait(monkeypatch):
    monkeypatch.setattr(ai_video, "get_task", lambda _id: {"status": "SUCCEEDED", "output": ["https://example.org/clip.mp4"]})
    assert ai_video.wait_task("task123") == "https://example.org/clip.mp4"
