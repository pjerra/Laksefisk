"""
Monitors WoW's chat log for loot messages and tracks fish catches.

Requires /chatlog to be enabled in WoW.
Parses lines like:
  "You receive loot: [Raw Brilliant Smallfish]x2."
  "You receive loot: [Longjaw Mud Snapper]."
"""

import glob
import logging
import os
import re
import threading
import time
from collections import Counter
from typing import Callable, List, Optional

logger = logging.getLogger("Laksefisk")

# Matches loot lines in WoW chat log.
# Format: "You receive loot: Item Name."  or  "You receive loot: [Item Name]x2."
# Classic Anniversary uses no brackets: "You receive loot: Raw Longjaw Mud Snapper."
_LOOT_RE = re.compile(r"You receive loot: \[?(.+?)\]?(?:x(\d+))?\.")


def find_wow_log_path() -> Optional[str]:
    """Search common WoW install locations for the chat log directory."""
    candidates = []
    for drive in ["C", "D", "E", "F"]:
        base = f"{drive}:/Program Files (x86)/World of Warcraft"
        if not os.path.isdir(base):
            base = f"{drive}:/Program Files/World of Warcraft"
        if not os.path.isdir(base):
            continue
        for variant in ["_anniversary_", "_classic_era_", "_classic_", "_retail_"]:
            logs_dir = os.path.join(base, variant, "Logs")
            if os.path.isdir(logs_dir):
                candidates.append(logs_dir)
            elif os.path.isdir(os.path.join(base, variant)):
                candidates.append(os.path.join(base, variant, "Logs"))

    # Return the first one that has a chat log, or the first candidate
    for c in candidates:
        log_file = os.path.join(c, "WoWChatLog.txt")
        if os.path.isfile(log_file):
            return log_file

    # Return first candidate path even if log doesn't exist yet
    if candidates:
        return os.path.join(candidates[0], "WoWChatLog.txt")
    return None


class FishTracker:
    """Tails WoW's chat log and counts looted items."""

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = log_path or find_wow_log_path()
        self._counts: Counter = Counter()
        self._total: int = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_update: Optional[Callable[[], None]] = None
        self._file_pos: int = 0

    @property
    def total(self) -> int:
        with self._lock:
            return self._total

    def get_stats(self) -> List[tuple]:
        """Returns list of (name, count, percentage) sorted by count descending."""
        with self._lock:
            total = self._total
            items = list(self._counts.items())
        if total == 0:
            return []
        items.sort(key=lambda x: x[1], reverse=True)
        return [(name, count, count / total * 100) for name, count in items]

    def set_on_update(self, callback: Callable[[], None]):
        self._on_update = callback

    def start(self):
        if self._running:
            return
        if not self.log_path:
            logger.warning("No WoW chat log path found. Enable /chatlog in WoW.")
            return
        self._running = True
        # Start reading from end of file (only new loot)
        if os.path.isfile(self.log_path):
            self._file_pos = os.path.getsize(self.log_path)
        else:
            self._file_pos = 0
        self._thread = threading.Thread(target=self._tail_loop, daemon=True)
        self._thread.start()
        logger.info(f"Fish tracker watching: {self.log_path}")

    def stop(self):
        self._running = False

    def reset(self):
        with self._lock:
            self._counts.clear()
            self._total = 0
        if self._on_update:
            self._on_update()

    def _tail_loop(self):
        while self._running:
            try:
                if not os.path.isfile(self.log_path):
                    time.sleep(2)
                    continue

                # Always try to read — WoW buffers writes so getsize() may
                # not reflect new data yet.  Open with sharing so WoW can
                # keep writing.
                with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                    f.seek(self._file_pos)
                    new_data = f.read()
                    new_pos = f.tell()

                if new_pos < self._file_pos:
                    # File was truncated/rotated — re-read from start
                    self._file_pos = 0
                    continue

                if new_data:
                    self._file_pos = new_pos
                    found = False
                    for line in new_data.splitlines():
                        m = _LOOT_RE.search(line)
                        if m:
                            item_name = m.group(1)
                            qty = int(m.group(2)) if m.group(2) else 1
                            with self._lock:
                                self._counts[item_name] += qty
                                self._total += qty
                            found = True
                            logger.info(f"Looted: {item_name} x{qty}")

                    if found and self._on_update:
                        self._on_update()

            except Exception as e:
                logger.debug(f"Fish tracker error: {e}")

            time.sleep(0.5)
