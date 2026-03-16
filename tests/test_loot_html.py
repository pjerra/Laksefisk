"""
Test: Generate a preview loot.html with interactive charts and collapsible sessions.
Opens the file in the browser after generating.
"""

import json
import os
import sys
import webbrowser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from loot_report import generate_loot_html

PREVIEW_PATH = os.path.join(os.path.dirname(__file__), "..", "loot_preview.html")


def make_sample_data():
    return {
        "all_time": {
            "total": 47,
            "items": [
                {"name": "Raw Bristle Whisker Catfish", "count": 18, "pct": 38.3},
                {"name": "Deviate Fish", "count": 12, "pct": 25.5},
                {"name": "Raw Longjaw Mud Snapper", "count": 9, "pct": 19.1},
                {"name": "17 Pound Catfish", "count": 4, "pct": 8.5},
                {"name": "Raw Brilliant Smallfish", "count": 3, "pct": 6.4},
                {"name": "Old Boot", "count": 1, "pct": 2.1},
            ]
        },
        "sessions": [
            {
                "start": "2026-03-08T19:30:12",
                "end": "2026-03-08T20:45:33",
                "total": 15,
                "items": [
                    {"name": "Raw Bristle Whisker Catfish", "count": 6, "pct": 40.0},
                    {"name": "Deviate Fish", "count": 4, "pct": 26.7},
                    {"name": "Raw Longjaw Mud Snapper", "count": 3, "pct": 20.0},
                    {"name": "Raw Brilliant Smallfish", "count": 2, "pct": 13.3},
                ]
            },
            {
                "start": "2026-03-09T14:10:05",
                "end": "2026-03-09T15:22:18",
                "total": 19,
                "items": [
                    {"name": "Raw Bristle Whisker Catfish", "count": 8, "pct": 42.1},
                    {"name": "Deviate Fish", "count": 5, "pct": 26.3},
                    {"name": "Raw Longjaw Mud Snapper", "count": 4, "pct": 21.1},
                    {"name": "17 Pound Catfish", "count": 2, "pct": 10.5},
                ]
            },
            {
                "start": "2026-03-10T22:00:44",
                "end": "2026-03-10T23:15:09",
                "total": 13,
                "items": [
                    {"name": "Raw Bristle Whisker Catfish", "count": 4, "pct": 30.8},
                    {"name": "Deviate Fish", "count": 3, "pct": 23.1},
                    {"name": "Raw Longjaw Mud Snapper", "count": 2, "pct": 15.4},
                    {"name": "17 Pound Catfish", "count": 2, "pct": 15.4},
                    {"name": "Raw Brilliant Smallfish", "count": 1, "pct": 7.7},
                    {"name": "Old Boot", "count": 1, "pct": 7.7},
                ]
            }
        ]
    }


if __name__ == "__main__":
    data = make_sample_data()
    html = generate_loot_html(data)
    with open(PREVIEW_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Preview saved to: {PREVIEW_PATH}")
    webbrowser.open(PREVIEW_PATH)
