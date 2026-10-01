from backend.app.services.stock import (
    _choose_pexels_file,
    _choose_pixabay_variant,
    _is_obvious_mismatch,
    _score_candidate,
    build_review_queries,
    build_search_query,
    candidate_key,
    first_unused_candidate,
    normalize_providers,
    promote_unused_candidate,
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



def test_first_unused_candidate_skips_duplicate_video_id():
    used = {("pexels", "100")}
    candidates = [
        {"provider": "pexels", "id": "100"},
        {"provider": "pexels", "id": "101"},
        {"provider": "pixabay", "id": "200"},
    ]
    selected = first_unused_candidate(candidates, used)
    assert candidate_key(selected) == ("pexels", "101")


def test_promote_unused_candidate_makes_review_default_unique():
    used = {("pexels", "100")}
    candidates = [
        {"provider": "pexels", "id": "100"},
        {"provider": "pexels", "id": "101"},
        {"provider": "pexels", "id": "102"},
    ]
    reordered = promote_unused_candidate(candidates, used)
    assert candidate_key(reordered[0]) == ("pexels", "101")
    assert {candidate_key(item) for item in reordered} == {
        ("pexels", "100"),
        ("pexels", "101"),
        ("pexels", "102"),
    }



def test_workspace_does_not_trigger_space_theme():
    query = build_search_query(
        "The agent can work across connected business apps.",
        fallback="OpenAI Dots always-on AI agent futuristic digital workspaces",
    )
    assert "rocket" not in query
    assert "spacecraft" not in query
    assert "artificial" in query


def test_review_and_render_use_same_search_context():
    script = "It can work across connected business apps."
    title = "OpenAI Dots Always-On AI Agent"
    prompt = "Futuristic digital workspaces and cloud computers."
    preview = build_review_queries(
        script,
        title,
        max_clips=1,
        prompt=prompt,
    )[0]["query"]
    render = build_search_query(
        script,
        fallback=f"{title} {prompt}",
    )
    assert preview == render
