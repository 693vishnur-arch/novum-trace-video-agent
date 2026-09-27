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
USER_AGENT = "NovumTraceVideoAgent/1.2"
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
    (("cyber", "cybersecurity", "hacker", "attack", "malware", "threat"), "cybersecurity hacker computer"),
    (("dns", "network", "internet", "online"), "computer network data center"),
    (("ai agent", "artificial intelligence", "openai", "chatbot", "model"), "artificial intelligence computer technology"),
    (("medical", "medicare", "hospital", "health"), "medical technology data"),
    (("government", "federal", "authority"), "government technology security"),
    (("file", "files", "transfer", "data"), "secure data transfer computer"),
    (("space", "nasa", "rocket", "satellite"), "space technology satellite"),
    (("robot", "robotics"), "robot artificial intelligence"),
]


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
        for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text)
        if token.lower() not in STOPWORDS
    ]


def build_search_query(text: str, fallback: str = "") -> str:
    """Turn narration text into a stock-friendly visual query.

    Search libraries work better with visual concepts such as "server room" than
    with complete news sentences. Domain concept rules take priority, then a
    compact keyword query is used.
    """
    source = re.sub(r"\s+", " ", (text or fallback).strip()).lower()
    if not source:
        return "technology data center"

    matched: list[str] = []
    for triggers, query in CONCEPT_RULES:
        if any(trigger in source for trigger in triggers):
            if query not in matched:
                matched.append(query)
        if len(matched) >= 2:
            break

    if matched:
        # Blend two concepts when useful, but cap the query length.
        combined = " ".join(matched)
        words: list[str] = []
        for word in combined.split():
            if word not in words:
                words.append(word)
        return " ".join(words[:6])

    tokens = _tokenize(source)
    unique: list[str] = []
    for token in tokens:
        if token not in unique:
            unique.append(token)
        if len(unique) >= 5:
            break
    return " ".join(unique) if unique else "technology data center"


def build_review_queries(script: str, title: str, max_clips: int = 6) -> list[dict[str, Any]]:
    max_clips = min(max(int(max_clips or 1), 1), 8)
    sentences = [
        re.sub(r"\s+", " ", part.strip())
        for part in re.split(r"(?<=[.!?])\s+|\n+", script or "")
        if part.strip()
    ]
    if not sentences:
        sentences = [title or "technology news"]

    if len(sentences) <= max_clips:
        groups = sentences
    else:
        per = math.ceil(len(sentences) / max_clips)
        groups = [" ".join(sentences[i:i + per]) for i in range(0, len(sentences), per)]

    return [
        {
            "scene_index": index,
            "text": text,
            "query": build_search_query(text, fallback=title),
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
    }


def search_pexels(query: str, *, limit: int = DEFAULT_RESULTS_PER_PROVIDER, prefer_portrait: bool = True) -> list[dict[str, Any]]:
    key = os.getenv("PEXELS_API_KEY", "").strip()
    if not key:
        return []

    params = {
        "query": query,
        "per_page": str(min(max(limit, 3), 20)),
        "size": "medium",
    }
    if prefer_portrait:
        params["orientation"] = "portrait"

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
        "per_page": str(min(max(limit, 3), 20)),
    }
    data = _json_request(f"{PIXABAY_API}?{urllib.parse.urlencode(params)}")
    result: list[dict[str, Any]] = []
    for hit in data.get("hits") or []:
        candidate = _pixabay_candidate(hit, query, prefer_portrait=prefer_portrait)
        if candidate:
            result.append(candidate)
    return result


def _score_candidate(candidate: dict[str, Any], prefer_portrait: bool = True) -> float:
    width = int(candidate.get("width") or 0)
    height = int(candidate.get("height") or 0)
    duration = float(candidate.get("duration") or 0)
    score = 0.0
    if prefer_portrait and height >= width:
        score += 30
    if min(width, height) >= 720:
        score += 18
    elif min(width, height) >= 540:
        score += 8
    if 3 <= duration <= 20:
        score += 10
    elif duration > 0:
        score += 3
    score += min(float(candidate.get("likes") or 0) / 200.0, 8.0)
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
        item["score"] = round(_score_candidate(item, prefer_portrait=prefer_portrait), 2)
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
