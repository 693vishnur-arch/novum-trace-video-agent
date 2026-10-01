from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

PEXELS_API = "https://api.pexels.com/v1/videos"
PIXABAY_API = "https://pixabay.com/api/videos/"
USER_AGENT = "NovumTraceVideoAgent/1.4.2"
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024
DEFAULT_RESULTS_PER_PROVIDER = 6

STOPWORDS = {
    "a", "about", "after", "again", "all", "also", "an", "and", "are", "as", "at",
    "be", "because", "been", "before", "being", "but", "by", "can", "could", "did",
    "do", "does", "doing", "down", "during", "each", "for", "from", "had", "has",
    "have", "here", "how", "if", "in", "into", "is", "it", "its", "just", "more",
    "most", "new", "no", "not", "now", "of", "on", "once", "one", "only", "or",
    "other", "our", "out", "over", "said", "says", "so", "some", "than", "that",
    "the", "their", "them", "then", "there", "these", "they", "this", "those",
    "through", "to", "too", "under", "up", "very", "was", "we", "were", "what",
    "when", "where", "which", "while", "who", "why", "will", "with", "would",
    "you", "your",
}

CONCEPT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("server", "servers", "data center", "datacenter"), "server room data center"),
    (("cyber", "cybersecurity", "hacker", "attack", "malware", "threat"), "cybersecurity computer security"),
    (("dns", "network", "internet", "online"), "computer network technology"),
    (("ai agent", "artificial intelligence", "openai", "chatbot", "model"), "artificial intelligence computer"),
    (("medical", "medicare", "hospital", "health"), "medical technology hospital"),
    (("government", "federal", "authority"), "government technology security"),
    (("file", "files", "transfer", "data"), "secure data transfer computer"),
    (("space", "spacex", "starship", "starbase", "starlink", "nasa", "rocket", "satellite"), "rocket spacecraft space"),
    (("robot", "robotics"), "robot artificial intelligence"),
]

SPACE_TERMS = (
    "space", "spacex", "starship", "starbase", "starlink", "nasa", "rocket",
    "satellite", "orbit", "orbital", "spacecraft", "reentry",
)
CYBER_TERMS = (
    "cyber", "cybersecurity", "hacker", "malware", "ransomware", "server",
    "dns", "network attack", "zero-day", "security warning",
)
AI_TERMS = ("ai agent", "artificial intelligence", "openai", "chatbot", "language model")
MEDICAL_TERMS = ("medical", "hospital", "health", "doctor", "patient", "medicare")
ROBOT_TERMS = ("robot", "robotics", "humanoid")

THEME_POSITIVE_TERMS: dict[str, set[str]] = {
    "space": {
        "rocket", "space", "spacecraft", "satellite", "orbit", "orbital", "launch",
        "astronaut", "earth", "moon", "mars", "engine", "reentry",
    },
    "cyber": {
        "cyber", "cybersecurity", "computer", "server", "network", "hacker",
        "security", "data", "code", "malware",
    },
    "ai": {
        "ai", "artificial", "intelligence", "computer", "robot", "technology",
        "digital", "chatbot", "data",
    },
}

THEME_NEGATIVE_TERMS: dict[str, set[str]] = {
    "space": {
        "football", "soccer", "basketball", "stadium", "tennis", "airplane", "aeroplane",
        "aircraft", "airport", "kitchen", "cooking", "wedding", "fashion", "restaurant",
        "food", "train", "bus", "motorcycle",
    },
    "cyber": {
        "football", "soccer", "basketball", "stadium", "kitchen", "cooking", "wedding",
        "fashion", "restaurant", "food", "beach", "forest",
    },
}


class StockProviderError(RuntimeError):
    pass


def api_status() -> dict[str, bool]:
    return {
        "pexels": bool(os.getenv("PEXELS_API_KEY", "").strip()),
        "pixabay": bool(os.getenv("PIXABAY_API_KEY", "").strip()),
    }


def normalize_providers(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        requested = ["pexels", "pixabay"]
    elif isinstance(value, str):
        requested = [item.strip().lower() for item in value.split(",") if item.strip()]
    else:
        requested = [str(item).strip().lower() for item in value if str(item).strip()]

    result: list[str] = []
    for provider in requested:
        if provider in {"pexels", "pixabay"} and provider not in result:
            result.append(provider)
    return result or ["pexels", "pixabay"]


def candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    return (
        str(candidate.get("provider") or "").strip().lower(),
        str(candidate.get("id") or "").strip(),
    )


def first_unused_candidate(
    candidates: Iterable[dict[str, Any]],
    used_ids: set[tuple[str, str]],
) -> dict[str, Any] | None:
    for candidate in candidates:
        key = candidate_key(candidate)
        if key[0] and key[1] and key not in used_ids:
            return candidate
    return None


def promote_unused_candidate(
    candidates: list[dict[str, Any]],
    used_ids: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Move the best not-yet-used result to the front for review-mode defaults."""
    candidate = first_unused_candidate(candidates, used_ids)
    if candidate is None:
        return candidates
    key = candidate_key(candidate)
    return [candidate, *[item for item in candidates if candidate_key(item) != key]]


def _json_request(url: str, *, headers: dict[str, str] | None = None, timeout: int = 18) -> dict[str, Any]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(400).decode("utf-8", errors="ignore")
        except Exception:
            pass
        raise StockProviderError(f"Stock provider HTTP {exc.code}: {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise StockProviderError(f"Stock provider connection failed: {exc.reason}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise StockProviderError("Stock provider returned invalid JSON") from exc


def _tokenize(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", text.replace("-", " ").replace("_", " "))
        if token.lower() not in STOPWORDS
    ]


def _match_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _contains_term(source: str, term: str) -> bool:
    """Match complete words/phrases, never arbitrary substrings.

    Example: "space" must match "space technology" but not "workspaces".
    Token matching also treats hyphens as phrase separators, so "zero-day"
    and "zero day" are equivalent for concept detection.
    """
    source_tokens = _match_tokens(source)
    term_tokens = _match_tokens(term)
    if not term_tokens or len(term_tokens) > len(source_tokens):
        return False
    size = len(term_tokens)
    return any(source_tokens[index:index + size] == term_tokens
               for index in range(len(source_tokens) - size + 1))


def _contains_any(source: str, terms: Iterable[str]) -> bool:
    return any(_contains_term(source, term) for term in terms)


def _visual_theme(text: str, fallback: str = "") -> str:
    combined = re.sub(r"\s+", " ", f"{text} {fallback}".strip()).lower()
    if _contains_any(combined, SPACE_TERMS):
        return "space"
    # Explicit AI-agent language wins over generic network/DNS words.
    if _contains_any(combined, AI_TERMS):
        return "ai"
    if _contains_any(combined, CYBER_TERMS):
        return "cyber"
    if _contains_any(combined, MEDICAL_TERMS):
        return "medical"
    if _contains_any(combined, ROBOT_TERMS):
        return "robotics"
    return ""


def build_search_query(text: str, fallback: str = "") -> str:
    """Turn narration into a concrete visual-search phrase.

    V1.3 keeps the overall story theme from the title/prompt even when an
    individual sentence is vague. Scene-specific cues then choose a visual
    concept. This prevents literal searches such as "today" or "Texas" from
    overpowering the actual subject of the Short.
    """
    scene = re.sub(r"\s+", " ", text.strip()).lower()
    context = re.sub(r"\s+", " ", fallback.strip()).lower()
    source = scene or context
    if not source:
        return "technology data center"

    theme = _visual_theme(scene, context)

    if theme == "space":
        if _contains_any(scene, ("satellite", "starlink", "deploy", "deployment")):
            return "satellite orbit earth"
        if _contains_any(scene, ("reentry", "re-entry", "atmosphere", "returning", "returned", "returns")):
            return "spacecraft reentry earth"
        if _contains_any(scene, ("orbit", "orbital", "suborbital")):
            return "spacecraft earth orbit"
        if _contains_any(scene, ("engine", "engines", "booster", "thrust")):
            return "rocket engine launch"
        if _contains_any(scene, ("launch", "launches", "launching", "launch pad", "starbase", "pad", "texas")):
            return "rocket launch pad"
        if _contains_any(scene, ("test flight", "flight", "trajectory")):
            return "rocket test flight"
        return "rocket spacecraft space"

    if theme == "cyber":
        if _contains_any(scene, ("server", "servers", "shutdown", "shut down", "data center")):
            return "server room data center"
        if _contains_any(scene, ("dns", "network", "internet", "online")):
            return "computer network cybersecurity"
        if _contains_any(scene, ("file", "files", "transfer")):
            return "secure data transfer computer"
        if _contains_any(scene, ("attack", "hacker", "malware", "threat", "warning", "alert")):
            return "cybersecurity security alert"
        return "cybersecurity computer security"

    if theme == "ai":
        if _contains_any(scene, ("internet", "dns", "network", "online")):
            return "artificial intelligence computer network"
        if _contains_any(scene, ("chatbot", "assistant")):
            return "ai chatbot computer"
        if _contains_any(scene, ("robot", "robotics")):
            return "ai robot technology"
        return "artificial intelligence computer"

    if theme == "medical":
        return "medical technology hospital"
    if theme == "robotics":
        return "robot artificial intelligence"

    combined_source = f"{scene} {context}".strip()
    for triggers, query in CONCEPT_RULES:
        if _contains_any(combined_source, triggers):
            return query

    tokens = _tokenize(scene or context)
    unique: list[str] = []
    for token in tokens:
        if token not in unique:
            unique.append(token)
        if len(unique) >= 5:
            break
    return " ".join(unique) if unique else "technology data center"


def build_review_queries(
    script: str,
    title: str,
    max_clips: int = 6,
    prompt: str = "",
) -> list[dict[str, Any]]:
    max_clips = min(max(int(max_clips or 1), 1), 8)
    from backend.app.services.planner import visual_groups

    groups = visual_groups(script or title or "technology news", max_clips)
    search_context = f"{title} {prompt}".strip()
    return [
        {
            "scene_index": index,
            "text": text,
            "query": build_search_query(text, fallback=search_context),
        }
        for index, text in enumerate(groups[:max_clips])
    ]


def _choose_pexels_file(video: dict[str, Any], prefer_portrait: bool = True) -> dict[str, Any] | None:
    choices: list[tuple[float, dict[str, Any]]] = []
    for item in video.get("video_files") or []:
        link = str(item.get("link") or "")
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if not link or width <= 0 or height <= 0:
            continue
        if item.get("file_type") and item.get("file_type") != "video/mp4":
            continue

        portrait = height >= width
        min_dim = min(width, height)
        target_penalty = abs(width - 720) + abs(height - 1280)
        if not portrait:
            target_penalty += 1500 if prefer_portrait else 100
        if min_dim < 540:
            target_penalty += 2500
        # Avoid downloading unnecessarily huge 4K assets on a tiny Render instance.
        if max(width, height) > 2200:
            target_penalty += 500
        choices.append((float(target_penalty), item))

    if not choices:
        return None
    choices.sort(key=lambda pair: pair[0])
    return choices[0][1]


def _pexels_candidate(video: dict[str, Any], query: str, prefer_portrait: bool = True) -> dict[str, Any] | None:
    selected = _choose_pexels_file(video, prefer_portrait=prefer_portrait)
    if not selected:
        return None
    width = int(selected.get("width") or video.get("width") or 0)
    height = int(selected.get("height") or video.get("height") or 0)
    duration = float(video.get("duration") or 0)
    user = video.get("user") or {}
    return {
        "provider": "pexels",
        "id": str(video.get("id")),
        "query": query,
        "page_url": str(video.get("url") or ""),
        "preview_url": str(video.get("image") or ""),
        "download_url": str(selected.get("link") or ""),
        "width": width,
        "height": height,
        "duration": duration,
        "creator": str(user.get("name") or "Pexels contributor"),
        "creator_url": str(user.get("url") or ""),
        "portrait": height >= width,
        "metadata_text": str(video.get("url") or ""),
    }


def search_pexels(query: str, *, limit: int = DEFAULT_RESULTS_PER_PROVIDER, prefer_portrait: bool = True) -> list[dict[str, Any]]:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return []

    # Relevance comes before framing. Hard-filtering Pexels to portrait can
    # remove the best rocket/server footage and leave unrelated vertical clips.
    # We search broadly, then score portrait as a preference.
    params = {
        "query": query,
        "per_page": str(min(max(limit * 3, 12), 40)),
        "size": "medium",
    }

    url = f"{PEXELS_API}/search?{urllib.parse.urlencode(params)}"
    data = _json_request(url, headers={"Authorization": key})
    result: list[dict[str, Any]] = []
    for video in data.get("videos") or []:
        candidate = _pexels_candidate(video, query, prefer_portrait=prefer_portrait)
        if candidate:
            result.append(candidate)
    return result


def _choose_pixabay_variant(hit: dict[str, Any], prefer_portrait: bool = True) -> dict[str, Any] | None:
    variants = hit.get("videos") or {}
    choices: list[tuple[float, dict[str, Any]]] = []
    for name in ("medium", "small", "large", "tiny"):
        item = variants.get(name) or {}
        url = str(item.get("url") or "")
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        size = int(item.get("size") or 0)
        if not url or width <= 0 or height <= 0:
            continue
        portrait = height >= width
        penalty = abs(width - 720) + abs(height - 1280)
        if prefer_portrait and not portrait:
            penalty += 1500
        if min(width, height) < 540:
            penalty += 1800
        if size > MAX_DOWNLOAD_BYTES:
            penalty += 5000
        choices.append((float(penalty), item))

    if not choices:
        return None
    choices.sort(key=lambda pair: pair[0])
    return choices[0][1]


def _pixabay_candidate(hit: dict[str, Any], query: str, prefer_portrait: bool = True) -> dict[str, Any] | None:
    selected = _choose_pixabay_variant(hit, prefer_portrait=prefer_portrait)
    if not selected:
        return None
    width = int(selected.get("width") or 0)
    height = int(selected.get("height") or 0)
    return {
        "provider": "pixabay",
        "id": str(hit.get("id")),
        "query": query,
        "page_url": str(hit.get("pageURL") or ""),
        "preview_url": str(selected.get("thumbnail") or ""),
        "download_url": str(selected.get("url") or ""),
        "width": width,
        "height": height,
        "duration": float(hit.get("duration") or 0),
        "creator": str(hit.get("user") or "Pixabay contributor"),
        "creator_url": "",
        "portrait": height >= width,
        "views": int(hit.get("views") or 0),
        "likes": int(hit.get("likes") or 0),
        "metadata_text": f"{hit.get('tags') or ''} {hit.get('pageURL') or ''}".strip(),
    }


def search_pixabay(query: str, *, limit: int = DEFAULT_RESULTS_PER_PROVIDER, prefer_portrait: bool = True) -> list[dict[str, Any]]:
    key = os.getenv("PIXABAY_API_KEY", "").strip()
    if not key:
        return []

    params = {
        "key": key,
        "q": query[:100],
        "video_type": "all",
        "safesearch": "true",
        "order": "popular",
        "per_page": str(min(max(limit * 3, 12), 40)),
    }
    data = _json_request(f"{PIXABAY_API}?{urllib.parse.urlencode(params)}")
    result: list[dict[str, Any]] = []
    for hit in data.get("hits") or []:
        candidate = _pixabay_candidate(hit, query, prefer_portrait=prefer_portrait)
        if candidate:
            result.append(candidate)
    return result


def _candidate_metadata_tokens(candidate: dict[str, Any]) -> set[str]:
    return set(_tokenize(str(candidate.get("metadata_text") or "")))


def _is_obvious_mismatch(candidate: dict[str, Any], query: str) -> bool:
    theme = _visual_theme(query)
    negatives = THEME_NEGATIVE_TERMS.get(theme)
    if not negatives:
        return False
    metadata_tokens = _candidate_metadata_tokens(candidate)
    return bool(metadata_tokens & negatives)


def _score_candidate(
    candidate: dict[str, Any],
    query: str,
    prefer_portrait: bool = True,
) -> float:
    width = int(candidate.get("width") or 0)
    height = int(candidate.get("height") or 0)
    duration = float(candidate.get("duration") or 0)
    score = 0.0

    # Relevance must outweigh orientation. A relevant landscape rocket clip is
    # better than an unrelated portrait football/airplane clip.
    query_tokens = set(_tokenize(query))
    metadata_tokens = _candidate_metadata_tokens(candidate)
    overlap = query_tokens & metadata_tokens
    score += min(len(overlap) * 16.0, 48.0)

    theme = _visual_theme(query)
    positives = THEME_POSITIVE_TERMS.get(theme, set())
    positive_hits = metadata_tokens & positives
    score += min(len(positive_hits) * 8.0, 24.0)

    negatives = THEME_NEGATIVE_TERMS.get(theme, set())
    if metadata_tokens & negatives:
        score -= 100.0

    if prefer_portrait and height >= width:
        score += 16
    if min(width, height) >= 720:
        score += 12
    elif min(width, height) >= 540:
        score += 6
    if 3 <= duration <= 20:
        score += 8
    elif duration > 0:
        score += 2
    score += min(float(candidate.get("likes") or 0) / 250.0, 6.0)
    return score


def search_stock(
    query: str,
    *,
    providers: str | Iterable[str] | None = None,
    limit: int = 6,
    prefer_portrait: bool = True,
) -> list[dict[str, Any]]:
    requested = normalize_providers(providers)
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []

    for provider in requested:
        try:
            if provider == "pexels":
                candidates.extend(search_pexels(query, limit=limit, prefer_portrait=prefer_portrait))
            elif provider == "pixabay":
                candidates.extend(search_pixabay(query, limit=limit, prefer_portrait=prefer_portrait))
        except StockProviderError as exc:
            errors.append(f"{provider}: {exc}")

    # Deduplicate by provider/id and rank portrait, HD, sensible-duration clips first.
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, Any]] = []
    for item in candidates:
        key = (str(item.get("provider")), str(item.get("id")))
        if key in seen:
            continue
        seen.add(key)
        if _is_obvious_mismatch(item, query):
            continue
        item["score"] = round(
            _score_candidate(item, query, prefer_portrait=prefer_portrait),
            2,
        )
        unique.append(item)
    unique.sort(key=lambda item: float(item.get("score") or 0), reverse=True)

    if not unique and errors and not any(api_status().values()):
        raise StockProviderError("No stock API keys are configured")
    return unique


def get_candidate(provider: str, video_id: str, *, query: str = "", prefer_portrait: bool = True) -> dict[str, Any]:
    provider = provider.strip().lower()
    video_id = str(video_id).strip()
    if not video_id:
        raise StockProviderError("Missing stock video ID")

    if provider == "pexels":
        key = os.getenv("PEXELS_API_KEY", "").strip()
        if not key:
            raise StockProviderError("PEXELS_API_KEY is not configured")
        data = _json_request(f"{PEXELS_API}/videos/{urllib.parse.quote(video_id)}", headers={"Authorization": key})
        candidate = _pexels_candidate(data, query, prefer_portrait=prefer_portrait)
    elif provider == "pixabay":
        key = os.getenv("PIXABAY_API_KEY", "").strip()
        if not key:
            raise StockProviderError("PIXABAY_API_KEY is not configured")
        params = {"key": key, "id": video_id, "safesearch": "true"}
        data = _json_request(f"{PIXABAY_API}?{urllib.parse.urlencode(params)}")
        hits = data.get("hits") or []
        candidate = _pixabay_candidate(hits[0], query, prefer_portrait=prefer_portrait) if hits else None
    else:
        raise StockProviderError(f"Unsupported stock provider: {provider}")

    if not candidate:
        raise StockProviderError(f"Could not resolve {provider} video {video_id}")
    return candidate


def download_candidate(candidate: dict[str, Any], destination: Path) -> Path:
    url = str(candidate.get("download_url") or "")
    if not url.startswith("https://"):
        raise StockProviderError("Stock provider returned an invalid download URL")

    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length and content_length > MAX_DOWNLOAD_BYTES:
                raise StockProviderError(
                    f"Stock clip is too large ({content_length // (1024 * 1024)} MB); choose a smaller clip"
                )

            written = 0
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        handle.close()
                        destination.unlink(missing_ok=True)
                        raise StockProviderError("Stock clip exceeded the 60 MB safety limit")
                    handle.write(chunk)
    except urllib.error.URLError as exc:
        destination.unlink(missing_ok=True)
        raise StockProviderError(f"Could not download stock clip: {exc.reason}") from exc

    if not destination.exists() or destination.stat().st_size < 1024:
        destination.unlink(missing_ok=True)
        raise StockProviderError("Downloaded stock clip was empty")
    return destination


def credit_record(candidate: dict[str, Any], *, scene_index: int | None = None) -> dict[str, Any]:
    return {
        "scene_index": scene_index,
        "provider": str(candidate.get("provider") or ""),
        "video_id": str(candidate.get("id") or ""),
        "creator": str(candidate.get("creator") or ""),
        "creator_url": str(candidate.get("creator_url") or ""),
        "source_url": str(candidate.get("page_url") or ""),
        "query": str(candidate.get("query") or ""),
    }


def write_credits(path: Path, credits: list[dict[str, Any]]) -> None:
    lines = [
        "NOVUM TRACE - STOCK VIDEO SOURCES",
        "",
        "Pexels: https://www.pexels.com/",
        "Pixabay: https://pixabay.com/",
        "",
    ]
    for index, credit in enumerate(credits, start=1):
        provider = credit.get("provider") or "stock"
        creator = credit.get("creator") or "contributor"
        source = credit.get("source_url") or ""
        query = credit.get("query") or ""
        lines.append(f"{index}. {provider.title()} - {creator}")
        if query:
            lines.append(f"   Search: {query}")
        if source:
            lines.append(f"   Source: {source}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
