#!/usr/bin/env python3
"""Search timestamped transcript segments and print surrounding evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def chinese_to_simplified(text: str) -> str:
    try:
        from opencc import OpenCC

        return OpenCC("t2s").convert(text)
    except ImportError:
        return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("meeting_json", type=Path)
    parser.add_argument("query", help="Space-separated terms or a phrase")
    parser.add_argument("--context", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def tokens(text: str) -> list[str]:
    phrase = chinese_to_simplified(text.strip()).casefold()
    if not phrase:
        return []
    parts = re.findall(r"[\w.-]+|[\u3400-\u9fff]", phrase)
    return list(dict.fromkeys([phrase, *parts]))


def score_segment(segment: dict[str, Any], terms: list[str]) -> int:
    text = chinese_to_simplified(segment.get("text", "")).casefold()
    exact = sum((4 if term == terms[0] else 1) * text.count(term) for term in terms)
    fuzzy = 0
    try:
        from rapidfuzz import fuzz

        candidates = []
        for term in terms:
            if len(term) < 2:
                continue
            ratio = round(fuzz.partial_ratio(term, text))
            threshold = 65 if len(term) == 3 else 72
            if ratio >= threshold:
                candidates.append(ratio)
        fuzzy = max(candidates, default=0)
    except ImportError:
        pass
    return exact * 100 + fuzzy


def main() -> None:
    args = parse_args()
    data = json.loads(args.meeting_json.read_text(encoding="utf-8"))
    segments = data.get("segments", [])
    query_terms = tokens(args.query)
    if not query_terms:
        raise SystemExit("Query is empty.")

    ranked = [
        (score_segment(segment, query_terms), index)
        for index, segment in enumerate(segments)
    ]
    matches = [(score, index) for score, index in ranked if score > 0]
    matches.sort(key=lambda item: (-item[0], item[1]))
    if not matches:
        print("No matching transcript segments.")
        return

    shown: set[int] = set()
    for score, hit_index in matches[: args.limit]:
        if hit_index in shown:
            continue
        start = max(0, hit_index - args.context)
        end = min(len(segments), hit_index + args.context + 1)
        block = [index for index in range(start, end) if index not in shown]
        if not block:
            continue
        print(f"\n--- hit score={score} ---")
        for index in block:
            segment = segments[index]
            marker = ">" if index == hit_index else " "
            speaker = f" {segment['speaker']}" if segment.get("speaker") else ""
            print(
                f"{marker} S{segment.get('id', index + 1):04d}"
                f" [{timestamp(segment['start'])}-{timestamp(segment['end'])}]"
                f"{speaker} {segment['text']}"
            )
            shown.add(index)


if __name__ == "__main__":
    main()
