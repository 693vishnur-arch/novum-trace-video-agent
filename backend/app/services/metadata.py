from __future__ import annotations

import re


def build_metadata(title: str, prompt: str, script: str) -> dict[str, str | list[str]]:
    clean_title = re.sub(r"\s+", " ", title).strip() or "Novum Trace Short"
    source = re.sub(r"\s+", " ", (prompt or script)).strip()
    summary = source[:320].rstrip()
    if len(source) > 320:
        summary += "..."
    description = (
        f"{summary}\n\n"
        "Follow Novum Trace for fast stories across AI, cybersecurity, science, space and the future.\n\n"
        "#AI #Cybersecurity #Technology #Science #Space #NovumTrace #Shorts"
    )
    return {
        "title": clean_title[:100],
        "description": description,
        "hashtags": ["#AI", "#Cybersecurity", "#Technology", "#NovumTrace", "#Shorts"],
        "pinned_comment": "What do you think happens next?",
    }
