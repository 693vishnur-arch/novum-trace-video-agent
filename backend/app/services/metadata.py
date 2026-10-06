from __future__ import annotations

import re


def build_metadata(
    title: str,
    prompt: str,
    script: str,
    video_mode: str = "short",
) -> dict[str, str | list[str]]:
    long_mode = video_mode == "long"
    clean_title = re.sub(r"\s+", " ", title).strip() or (
        "Novum Trace Video" if long_mode else "Novum Trace Short"
    )
    source = re.sub(r"\s+", " ", (prompt or script)).strip()
    summary = source[:420 if long_mode else 320].rstrip()
    if len(source) > len(summary):
        summary += "..."

    hashtags = ["#AI", "#Cybersecurity", "#Technology", "#NovumTrace"]
    if not long_mode:
        hashtags.append("#Shorts")

    description = (
        f"{summary}\n\n"
        "Follow Novum Trace for stories across AI, cybersecurity, science, space and the future.\n\n"
        + " ".join(hashtags)
    )
    return {
        "title": clean_title[:100],
        "description": description,
        "hashtags": hashtags,
        "pinned_comment": "What do you think happens next?",
    }
