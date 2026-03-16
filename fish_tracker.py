"""
Fish loot tracker — pixel bridge mode only.

Records loot events from the WoW Laksefisk addon via the pixel bridge.
Persists session and all-time totals to a JSON file.
"""

import json
import logging
import os
import threading
import unicodedata
from collections import Counter
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("Laksefisk")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_key(name: str) -> str:
    """Key for grouping: lowercase, no apostrophes, no accents."""
    normalized = "".join(
        c if unicodedata.category(c) != "Mn" else ""
        for c in unicodedata.normalize("NFD", name)
    )
    return normalized.replace("'", "").replace("\u2019", "").lower()


# ---------------------------------------------------------------------------
# FishTracker
# ---------------------------------------------------------------------------

class FishTracker:
    """Pixel-bridge fish tracker.

    Records loot events from the addon pixel bridge.  Persists session
    and all-time totals to a JSON file.
    """

    def __init__(self, loot_file: Optional[str] = None):
        self._counts: Counter = Counter()
        self._names: Dict[str, str] = {}  # key -> best display name
        self._total: int = 0

        self._lock = threading.Lock()
        self._on_update: Optional[Callable[[], None]] = None

        self.loot_file: Optional[str] = loot_file
        self._session_start: str = datetime.now().isoformat(timespec="seconds")

    @property
    def total(self) -> int:
        with self._lock:
            return self._total

    def get_stats(self) -> List[tuple]:
        """Returns list of (name, count, percentage) sorted by count desc."""
        with self._lock:
            total = self._total
            items = [
                (self._names.get(k, k), c)
                for k, c in self._counts.items()
            ]
        if total == 0:
            return []
        items.sort(key=lambda x: x[1], reverse=True)
        return [(name, count, count / total * 100) for name, count in items]

    def set_on_update(self, callback: Callable[[], None]):
        self._on_update = callback

    def reset(self):
        with self._lock:
            self._counts.clear()
            self._names.clear()
            self._total = 0
        if self._on_update:
            self._on_update()

    # -- Pixel bridge (called by bot after each loot) -----------------------

    def record_pixel_loot(self, name: str, item_id: int = 0):
        """Record a loot event from the pixel bridge (exact item name)."""
        if not name:
            return
        key = _normalize_key(name)
        with self._lock:
            self._counts[key] += 1
            self._total += 1
            self._names[key] = name  # pixel bridge gives exact names
        logger.info(f"Pixel Looted: [{name}] (ID: {item_id})")
        self.save_loot()
        if self._on_update:
            self._on_update()

    # -- Persistence ---------------------------------------------------------

    def _items_with_pct(self, counts: Counter, total: int) -> List[Dict]:
        """Build items list with count and percentage."""
        items = []
        for name, count in counts.most_common():
            pct = round(count / total * 100, 1) if total else 0
            items.append({"name": name, "count": count, "pct": pct})
        return items

    def save_loot(self):
        """Save current session + all-time totals to JSON file.

        File structure:
          all_time:   {total, items[{name, count, pct}]}
          sessions:   [{start, end, total, items[{name, count, pct}]}]
        """
        if not self.loot_file:
            return

        # Load existing data to merge sessions
        existing = self._load_raw()
        prev_sessions = existing.get("sessions", [])

        # Build current session data
        with self._lock:
            sess_total = self._total
            sess_counts = Counter({
                self._names.get(k, k): c
                for k, c in self._counts.items()
            })

        if sess_total == 0:
            return

        now = datetime.now().isoformat(timespec="seconds")
        current_session = {
            "start": self._session_start,
            "end": now,
            "total": sess_total,
            "items": self._items_with_pct(sess_counts, sess_total),
        }

        # Update or append current session
        updated = False
        for i, s in enumerate(prev_sessions):
            if s.get("start") == self._session_start:
                prev_sessions[i] = current_session
                updated = True
                break
        if not updated:
            prev_sessions.append(current_session)

        # Build all-time totals from all sessions
        all_time_counts: Counter = Counter()
        for s in prev_sessions:
            for item in s["items"]:
                all_time_counts[item["name"]] += item["count"]
        all_time_total = sum(all_time_counts.values())

        data = {
            "all_time": {
                "total": all_time_total,
                "items": self._items_with_pct(all_time_counts, all_time_total),
            },
            "sessions": prev_sessions,
        }

        try:
            with open(self.loot_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"Failed to save loot file: {e}")

        # Also generate HTML report
        try:
            from loot_report import generate_loot_html
            html_path = self.loot_file.rsplit(".", 1)[0] + ".html"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(generate_loot_html(data))
        except Exception as e:
            logger.debug(f"Failed to save loot HTML: {e}")

    def _load_raw(self) -> dict:
        """Load raw JSON from loot file."""
        if not self.loot_file or not os.path.isfile(self.loot_file):
            return {}
        try:
            with open(self.loot_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def load_loot(self):
        """Load loot data from JSON file (does NOT load previous sessions
        into current counters — current session starts fresh)."""
        data = self._load_raw()
        if not data:
            return

        all_time = data.get("all_time", {})
        total = all_time.get("total", 0)
        sessions = data.get("sessions", [])
        logger.info(f"Loot file: {total} fish across {len(sessions)} session(s)")
