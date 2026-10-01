from backend.app.models import Scene, WordTiming
from backend.app.services.captions import build_ass, split_caption_chunks


def _normalize(value: str) -> str:
    return " ".join(value.split())


def test_dynamic_caption_chunks_preserve_every_word():
    text = (
        "Kiteworks says it received credible threat intelligence warning of a "
        "possible attack this weekend."
    )
    chunks = split_caption_chunks(text)
    assert len(chunks) >= 2
    assert _normalize(" ".join(chunks)) == _normalize(text)
    assert "..." not in " ".join(chunks)


def test_build_ass_splits_long_scene_without_truncation(tmp_path):
    text = (
        "The shutdown is precautionary meant to protect systems before an attack "
        "happens and the safest move is simply turn the servers off."
    )
    scene = Scene(
        index=0,
        start=0.0,
        end=8.0,
        duration=8.0,
        text=text,
        clip_name="server.mp4",
        role="body",
    )
    output = tmp_path / "captions.ass"
    build_ass(
        [scene],
        output,
        hook="SERVER WARNING",
        ending_question="",
        total_duration=8.0,
    )
    ass = output.read_text(encoding="utf-8")

    body_events = [line for line in ass.splitlines() if ",Caption," in line]
    assert len(body_events) >= 2
    assert "off." in ass
    assert "..." not in ass



def test_end_card_suppresses_duplicate_body_caption(tmp_path):
    words = [
        WordTiming("Would", 6.0, 6.3),
        WordTiming("you", 6.3, 6.5),
        WordTiming("trust", 6.5, 6.8),
        WordTiming("it?", 6.8, 7.1),
    ]
    scene = Scene(
        index=0,
        start=0.0,
        end=8.0,
        duration=8.0,
        text="Would you trust it?",
        clip_name=None,
        role="ending",
        words=words,
    )
    output = tmp_path / "captions.ass"
    build_ass([scene], output, hook="", ending_question="Would you trust it?", total_duration=8.0)
    ass = output.read_text(encoding="utf-8")
    assert "Dialogue: 3,0:00:06.00,0:00:08.00,Ending" in ass
    assert not any(
        line.startswith("Dialogue: 0,0:00:06") and ",Caption," in line
        for line in ass.splitlines()
    )


def test_long_hook_wrap_does_not_widen_into_clipped_lines():
    from backend.app.services.captions import wrap_caption
    wrapped = wrap_caption(
        "OPENAI JUST LAUNCHED AN AI THAT NEVER CLOCKS OUT",
        width=18,
        max_lines=3,
    )
    assert max(len(line) for line in wrapped.splitlines()) <= 18
