import json

from backend.app import main as app_main
from backend.app.models import Scene


def _candidate(video_id: str) -> dict:
    return {
        "provider": "pexels",
        "id": video_id,
        "query": "artificial intelligence computer",
        "page_url": f"https://www.pexels.com/video/{video_id}/",
        "preview_url": "",
        "download_url": f"https://example.test/{video_id}.mp4",
        "width": 720,
        "height": 1280,
        "duration": 8,
        "creator": "Test",
        "creator_url": "",
        "portrait": True,
    }


def test_review_duplicates_are_replaced_and_stock_is_not_recycled(monkeypatch, tmp_path):
    scenes = [
        Scene(index=0, start=0, end=3, duration=3, text="AI agent one."),
        Scene(index=1, start=3, end=6, duration=3, text="AI agent two."),
        Scene(index=2, start=6, end=9, duration=3, text="AI agent three."),
    ]
    selections = json.dumps([
        {"scene_index": 0, "provider": "pexels", "id": "100", "query": "ai"},
        {"scene_index": 1, "provider": "pexels", "id": "100", "query": "ai"},
    ])

    monkeypatch.setattr(
        app_main,
        "stock_api_status",
        lambda: {"pexels": True, "pixabay": False},
    )
    monkeypatch.setattr(
        app_main,
        "get_candidate",
        lambda provider, video_id, **kwargs: _candidate(video_id),
    )

    def fake_search(*args, **kwargs):
        # Scene 1's duplicate reviewed choice should fall through to 101.
        # Scene 2 then has no unused result and must remain unmatched instead
        # of recycling 100 or 101.
        return [_candidate("100"), _candidate("101")]

    monkeypatch.setattr(app_main, "search_stock", fake_search)

    def fake_download(candidate, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"video")
        return destination

    monkeypatch.setattr(app_main, "download_candidate", fake_download)

    paths, credits = app_main._download_stock_for_scenes(
        project_dir=tmp_path,
        scenes=scenes,
        visual_paths=[],
        title="AI agents",
        prompt="",
        visual_source="stock_auto",
        providers="pexels",
        max_clips=3,
        selections_raw=selections,
        prefer_portrait=True,
    )

    assert len(paths) == 2
    assert len(credits) == 2
    assert "pexels_100" in scenes[0].clip_name
    assert "pexels_101" in scenes[1].clip_name
    assert scenes[2].clip_name is None
