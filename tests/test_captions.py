from backend.app.models import Scene
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
        ending_question="HOW SERIOUS IS THE THREAT?",
        total_duration=8.0,
    )
    ass = output.read_text(encoding="utf-8")

    body_events = [line for line in ass.splitlines() if ",Caption," in line]
    assert len(body_events) >= 2
    assert "turn the servers off." in ass
    assert "..." not in ass
