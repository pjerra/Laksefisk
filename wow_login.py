"""
Auto login/logout — automates WoW character select and /logout.

Detects screen state (in-world, character select, loading, no window)
using pixel bridge for in-world and colour sampling for character select.
All UI positions are relative to window size (resolution-independent).
"""

import logging
import random
import time
from typing import Optional, Tuple

import win32gui

import wow_process
from pixel_bridge import PixelBridge
from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")
_rng = random.Random()

# ---------------------------------------------------------------------------
# Character select screen detection
# ---------------------------------------------------------------------------
# Relative positions (fraction of client width/height) and expected RGB values
# for TBC Anniversary Classic character select screen.
#
# These MUST be measured from actual screenshots. Placeholder values below —
# update after capturing screenshots at character select.
#
# Each probe: (rel_x, rel_y, (R, G, B))
# ---------------------------------------------------------------------------
_CHARSELECT_PROBES: list[Tuple[float, float, Tuple[int, int, int]]] = [
    # "Enter World" button centre — gold/yellow text area
    (0.50, 0.91, (180, 160, 80)),
    # Character list background — dark pane left side
    (0.25, 0.50, (20, 15, 15)),
    # Bottom bar — dark UI frame below button
    (0.50, 0.96, (30, 25, 20)),
]
_COLOUR_TOLERANCE = 20  # per channel — matches pixel_bridge.py and spec

# Character slot relative positions
_CHAR_LIST_X = 0.50        # character names are centred horizontally
_CHAR_LIST_TOP_Y = 0.35    # first slot Y position (to be validated)
_CHAR_SLOT_SPACING = 0.055  # vertical spacing between slots (to be validated)

# "Enter World" button
_ENTER_WORLD_X = 0.50
_ENTER_WORLD_Y = 0.91


def _colour_match(actual: Tuple[int, int, int],
                  expected: Tuple[int, int, int],
                  tolerance: int = _COLOUR_TOLERANCE) -> bool:
    """Check if actual RGB is within tolerance of expected."""
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


class WowLogin:
    """Automates WoW character select login and /logout."""

    def __init__(self, wow_screen: WowScreen, pixel_bridge: PixelBridge):
        self._screen = wow_screen
        self._bridge = pixel_bridge

    def detect_state(self) -> str:
        """Detect current WoW screen state.

        Returns one of: 'in_world', 'character_select', 'unknown', 'no_window'.
        """
        # Try pixel bridge first — if it reads, we're in-world
        try:
            data = self._bridge.read()
            if data is not None:
                return "in_world"
        except Exception:
            pass

        # Check if WoW window exists
        img = self._screen.capture_full()
        if img is None:
            return "no_window"

        # Sample character select probe points
        try:
            w, h = img.size
            matches = 0
            for rel_x, rel_y, expected_rgb in _CHARSELECT_PROBES:
                px = int(rel_x * w)
                py = int(rel_y * h)
                px = max(0, min(px, w - 1))
                py = max(0, min(py, h - 1))
                actual = img.getpixel((px, py))[:3]
                if _colour_match(actual, expected_rgb):
                    matches += 1
            # Require at least 2 of 3 probes to match
            if matches >= 2:
                return "character_select"
        except Exception:
            pass
        finally:
            img.close()

        return "unknown"

    def _wait_for_state(self, target: str, timeout: float,
                        poll_interval: float = 1.5) -> bool:
        """Poll detect_state until target is reached or timeout expires."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.detect_state() == target:
                return True
            time.sleep(poll_interval)
        return False

    def _relative_to_screen(self, rel_x: float, rel_y: float) -> Tuple[int, int]:
        """Convert relative window position to absolute screen coordinates.

        Refreshes geometry via capture_full to ensure origin is current
        (handles window being moved between calls).
        """
        # Refresh geometry — capture_full calls _update_geometry internally
        img = self._screen.capture_full()
        if img is not None:
            img.close()
        w, h = self._screen.client_size
        origin = self._screen.client_origin
        px = int(rel_x * w) + origin[0] + _rng.randint(-3, 3)
        py = int(rel_y * h) + origin[1] + _rng.randint(-3, 3)
        return (px, py)
