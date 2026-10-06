from backend.app.config import video_profile
from backend.app.models import Scene, WordTiming
from backend.app.services.captions import build_ass
from backend.app.services.renderer import _video_filter
from backend.app.services.stock import build_review_queries


def test_video_profiles_preserve_short_and_add_long():
    short = video_profile("short")
    long = video_profile("long")
    assert (short["width"], short["height"], short["max_scenes"]) == (720, 1280, 8)
    assert (long["width"], long["height"], long["max_scenes"]) == (1280, 720, 36)


def test_long_stock_review_can_create_more_than_eight_scenes():
    script = " ".join(f"Scene {i} explains a different security point." for i in range(1, 21))
    # Add sentence punctuation so visual grouping sees 20 sentences.
    script = ". ".join(f"Scene {i} explains a different security point" for i in range(1, 21)) + "."
    queries = build_review_queries(script, "AI security documentary", max_clips=20)
    assert len(queries) == 20
    assert queries[0]["scene_index"] == 0
    assert queries[-1]["scene_index"] == 19


def test_long_video_filter_is_landscape():
    vf = _video_filter(1280, 720)
    assert "scale=1280:720" in vf
    assert "crop=1280:720" in vf


def test_long_caption_layout_is_16_9_and_sparse(tmp_path):
    scenes = []
    cursor = 0.0
    for index in range(8):
        words = [
            WordTiming(f"Scene{index}", cursor + 0.2, cursor + 0.5),
            WordTiming("important.", cursor + 0.6, cursor + 1.0),
        ]
        scenes.append(
            Scene(
                index=index,
                start=cursor,
                end=cursor + 2.0,
                duration=2.0,
                text=f"Scene{index} important.",
                clip_name=None,
                role="body",
                words=words,
            )
        )
        cursor += 2.0

    output = tmp_path / "long.ass"
    build_ass(
        scenes,
        output,
        hook="AI AGENTS ARE FINDING WAYS OUT",
        ending_question="CAN THE NEXT SANDBOX HOLD?",
        total_duration=16.0,
        video_mode="long",
    )
    ass = output.read_text(encoding="utf-8")
    assert "PlayResX: 1280" in ass
    assert "PlayResY: 720" in ass
    body_events = [line for line in ass.splitlines() if ",Caption," in line]
    assert len(body_events) <= 2
