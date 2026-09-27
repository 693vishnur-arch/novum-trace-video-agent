from backend.app.services.stock import (
    _choose_pexels_file,
    _choose_pixabay_variant,
    build_review_queries,
    build_search_query,
    normalize_providers,
)


def test_stock_query_prefers_visual_server_concept():
    query = build_search_query(
        "The company told customers to shut down their servers after a security warning."
    )
    assert "server" in query
    assert "data" in query


def test_stock_query_maps_ai_network_story():
    query = build_search_query(
        "An AI agent found a DNS route to the live internet from the sandbox."
    )
    assert "network" in query or "artificial" in query


def test_review_queries_respect_clip_cap():
    script = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine."
    queries = build_review_queries(script, "Test", max_clips=4)
    assert 1 <= len(queries) <= 4
    assert all(item["query"] for item in queries)


def test_provider_normalization():
    assert normalize_providers("pexels,pixabay,pexels") == ["pexels", "pixabay"]
    assert normalize_providers("bad") == ["pexels", "pixabay"]


def test_pexels_file_selection_prefers_portrait_hd():
    video = {
        "video_files": [
            {"link": "https://example.test/a.mp4", "width": 1920, "height": 1080, "file_type": "video/mp4"},
            {"link": "https://example.test/b.mp4", "width": 720, "height": 1280, "file_type": "video/mp4"},
        ]
    }
    selected = _choose_pexels_file(video, prefer_portrait=True)
    assert selected["link"].endswith("b.mp4")


def test_pixabay_variant_prefers_portrait_when_available():
    hit = {
        "videos": {
            "medium": {"url": "https://example.test/a.mp4", "width": 1920, "height": 1080, "size": 1000},
            "small": {"url": "https://example.test/b.mp4", "width": 720, "height": 1280, "size": 1000},
        }
    }
    selected = _choose_pixabay_variant(hit, prefer_portrait=True)
    assert selected["url"].endswith("b.mp4")
