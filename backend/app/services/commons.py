"""Conservative Wikimedia Commons discovery for reusable editorial still images.

Only explicitly CC0/public-domain assets are accepted automatically. Other licenses
require human review and are not downloaded by this module.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
MAX_BYTES = 18 * 1024 * 1024


def _plain(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", value or "")).strip()


def eligible(meta: dict) -> bool:
    license_name = _plain((meta.get("LicenseShortName") or {}).get("value", "")).casefold()
    return license_name in {"cc0", "public domain", "pd", "cc0 1.0"}


def search_images(query: str, limit: int = 8) -> list[dict]:
    params = {
        "action": "query", "generator": "search", "gsrsearch": query[:120] + " filetype:bitmap",
        "gsrnamespace": "6", "gsrlimit": str(min(max(limit, 1), 20)),
        "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
        "format": "json", "formatversion": "2",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "NovumTraceVideoAgent/1.6 (editorial research)"})
    with urllib.request.urlopen(req, timeout=18) as response:
        payload = json.load(response)
    results = []
    for page in payload.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        location = str(info.get("url") or "")
        mime = info.get("mime") or ""
        if (not eligible(meta) or mime not in {"image/jpeg", "image/png", "image/webp"}
                or not location.startswith("https://upload.wikimedia.org/")):
            continue
        if int(info.get("size") or 0) > MAX_BYTES:
            continue
        title = str(page.get("title") or "")
        results.append({
            "provider": "wikimedia_commons", "id": str(page.get("pageid") or title),
            "query": query, "download_url": location,
            "page_url": "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "license": _plain((meta.get("LicenseShortName") or {}).get("value", "")),
            "creator": _plain((meta.get("Artist") or {}).get("value", "")),
            "attribution": _plain((meta.get("Attribution") or {}).get("value", "")),
            "width": info.get("width"), "height": info.get("height"),
            "mime": mime, "reuse_review_required": True,
        })
    return results


def download_image(candidate: dict, destination: Path) -> Path:
    url = str(candidate["download_url"])
    if not url.startswith("https://upload.wikimedia.org/"):
        raise ValueError("Untrusted Commons download location")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NovumTraceVideoAgent/1.6"})
        with urllib.request.urlopen(req, timeout=40) as response, destination.open("wb") as output:
            count = 0
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                count += len(chunk)
                if count > MAX_BYTES:
                    raise ValueError("Commons image too large")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination
