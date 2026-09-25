from pathlib import Path

from backend.app.services.budget import GenerationBudget
from backend.app.services.planner import derive_hook, plan_scenes, split_sentences


def test_split_sentences():
    parts = split_sentences("One thing happened. Then another happened! Final question?")
    assert len(parts) == 3


def test_plan_scenes_matches_total_duration():
    clips = [Path("one.mp4"), Path("two.mp4")]
    scenes = plan_scenes(
        20.0,
        "An AI agent opened a portal. It found another route. The team disclosed the issue. The system was fixed.",
        clips,
    )
    assert scenes
    assert abs(scenes[-1].end - 20.0) < 0.01
    assert all(scene.duration > 0 for scene in scenes)
    assert all(scene.clip_name in {"one.mp4", "two.mp4"} for scene in scenes)


def test_budget_hard_limit():
    budget = GenerationBudget(maximum=1)
    assert budget.can_generate()
    budget.consume()
    assert budget.remaining == 0
    assert not budget.can_generate()


def test_hook_derived_from_script():
    hook = derive_hook("Fallback", "An AI agent crossed the security boundary without being asked.")
    assert hook.startswith("AN AI AGENT")
