from backend.app.services.stock import (
    _choose_pexels_file,
    _choose_pixabay_variant,
    _is_obvious_mismatch,
    _score_candidate,
    build_review_queries,
    build_search_query,
    normalize_providers,
)


def test_stock_query_prefers_visual_server_concept():
    query = build_search_query(
        "The company told customers to shut down their servers after a security warning."
    )
    assert query == "server room data center"


def test_stock_query_maps_ai_network_story():
    query = build_search_query(
        "An AI agent found a DNS route to the live internet from the sandbox."
    )
    assert "network" in query
    assert "artificial" in query


def test_starship_title_keeps_vague_scene_on_space_theme():
    query = build_search_query(
        "Today could be a huge day.",
        fallback="Starship First Orbital Flight Today",
    )
    assert query == "rocket spacecraft space"


def test_starbase_scene_maps_to_rocket_launch_pad():
    query = build_search_query(
        "Starship Flight 14 is scheduled to launch from Starbase in Texas.",
        fallback="Starship First Orbital Flight Today",
    )
    assert query == "rocket launch pad"


def test_orbit_scene_maps_to_spacecraft_orbit():
    query = build_search_query(
        "Starship is attempting to reach orbit for the first time.",
        fallback="Starship First Orbital Flight Today",
    )
    assert query == "spacecraft earth orbit"


def test_satellite_scene_maps_to_satellite_orbit():
    query = build_search_query(
        "It will deploy 26 next-generation Starlink satellites.",
        fallback="Starship First Orbital Flight Today",
    )
    assert query == "satellite orbit earth"


def test_reentry_scene_maps_to_reentry_visual():
    query = build_search_query(
        "Previous flights returned through the atmosphere.",
        fallback="Starship First Orbital Flight Today",
    )
    assert query == "spacecraft reentry earth"


def test_review_queries_use_requested_scene_cap():
    script = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine."
    queries = build_review_queries(script, "Starship First Orbital Flight Today", max_clips=8)
    assert len(queries) == 8
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


def test_space_search_rejects_football_and_airplane_metadata():
    football = {
        "metadata_text": "https://www.pexels.com/video/people-playing-football-in-a-stadium-12345/",
        "width": 720,
        "height": 1280,
        "duration": 8,
    }
    airplane = {
        "metadata_text": "https://www.pexels.com/video/airplane-wing-above-clouds-999/",
        "width": 720,
        "height": 1280,
        "duration": 8,
    }
    assert _is_obvious_mismatch(football, "rocket launch pad")
    assert _is_obvious_mismatch(airplane, "spacecraft earth orbit")


def test_relevant_landscape_rocket_beats_unrelated_portrait_clip():
    rocket = {
        "metadata_text": "rocket launch spacecraft space",
        "width": 1920,
        "height": 1080,
        "duration": 10,
        "likes": 0,
    }
    unrelated = {
        "metadata_text": "people walking city street",
        "width": 720,
        "height": 1280,
        "duration": 10,
        "likes": 0,
    }
    assert _score_candidate(rocket, "rocket launch pad", prefer_portrait=True) > _score_candidate(
        unrelated,
        "rocket launch pad",
        prefer_portrait=True,
    )
