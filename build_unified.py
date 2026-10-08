#!/usr/bin/env python3
"""Build the self-contained vocabulary card/editor from the saved default book."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "default-vocabulary.html"
TEMPLATE = ROOT / "unified-template.html"
OUTPUT_DIR = ROOT / "exe-assets"
OUTPUT = OUTPUT_DIR / "vocabulary-v001.html"
APP_VERSION = "1.10.0"


def extract_project(source: str) -> dict[str, object]:
    match = re.search(
        r'<script(?=[^>]*\btype=["\']application/json["\'])(?=[^>]*\bid=["\']app-data["\'])[^>]*>'
        r'([\s\S]*?)</script\s*>',
        source,
        flags=re.I,
    )
    if not match:
        raise RuntimeError("Default vocabulary file does not contain app-data")
    project = json.loads(match.group(1))
    words = project.get("words") if isinstance(project, dict) else None
    if project.get("schemaVersion") != 1 or not isinstance(words, list) or not words:
        raise RuntimeError("Default vocabulary data is not supported")
    if project.get("voice") != "en-US-GuyNeural":
        raise RuntimeError("Default vocabulary uses a different voice")
    seen: set[str] = set()
    for item in words:
        if not isinstance(item, dict) or not item.get("word") or not item.get("meaning"):
            raise RuntimeError("Default vocabulary contains an incomplete word")
        key = str(item["word"]).strip().casefold()
        if key in seen:
            raise RuntimeError(f"Default vocabulary contains a duplicate word: {item['word']}")
        seen.add(key)
        item["phraseTitle"] = str(item.get("phraseTitle") or "短语搭配")[:40]
        if item.get("audioText") != item["word"] or not str(item.get("audioData", "")).startswith(
            "data:audio/mpeg;base64,"
        ):
            raise RuntimeError(f"Default vocabulary is missing fixed audio: {item['word']}")
    project["appVersion"] = APP_VERSION
    return project


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")
    project = extract_project(source)
    payload = json.dumps(project, ensure_ascii=False, separators=(",", ":"))
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    output_html = template.replace("__APP_VERSION__", APP_VERSION).replace("__APP_DATA__", payload)
    if "__APP_VERSION__" in output_html or "__APP_DATA__" in output_html:
        raise RuntimeError("Template placeholder was not replaced")

    OUTPUT_DIR.mkdir(exist_ok=True)
    OUTPUT.write_text(output_html, encoding="utf-8", newline="\n")
    print(f"Built {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
