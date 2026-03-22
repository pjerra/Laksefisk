"""
Auto login/logout — automates WoW character select and /logout.

Detects screen state (in-world, character select, loading, no window)
using pixel bridge for in-world and colour sampling for character select.
All UI positions are relative to window size (resolution-independent).

Note: Character select detection uses ImageGrab (full-screen capture) because
PrintWindow does not capture the WoW UI overlay at the character select screen.
Click coordinates use the logical window size via WowScreen (for SetCursorPos).
"""

import logging
import random
import time
from typing import Tuple

from PIL import ImageGrab

import wow_process
from pixel_bridge import PixelBridge
from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")
_rng = random.Random()

# ---------------------------------------------------------------------------
# Character select screen detection
# ---------------------------------------------------------------------------
# Relative positions (fraction of screen) and expected RGB values for
# TBC Anniversary Classic character select screen.
#
# Measured from full-screen ImageGrab at 1920x1200 (125% DPI).
# Relative positions are resolution/DPI independent.
#
# Each probe: (rel_x, rel_y, (R, G, B))
# ---------------------------------------------------------------------------
_CHARSELECT_PROBES = [
    # "Enter World" button — red button at bottom centre
    (0.50, 0.92, (106, 6, 3)),
    # Character list panel background — dark gray on right side
    (0.85, 0.20, (25, 25, 25)),
    # Bottom bar area — dark brownish below Enter World
    (0.50, 0.95, (75, 69, 60)),
]
_COLOUR_TOLERANCE = 30  # per channel — generous for DPI/gamma variance

# Character slot positions (right-side panel in TBC Anniversary)
_CHAR_LIST_X = 0.85       # character list is on the right side
_CHAR_LIST_TOP_Y = 0.12   # first character entry Y
_CHAR_SLOT_SPACING = 0.06  # vertical spacing between entries

# "Enter World" button
_ENTER_WORLD_X = 0.50
_ENTER_WORLD_Y = 0.92


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

        Uses pixel bridge for in-world detection. Uses ImageGrab (full-screen
        capture) for character select detection because PrintWindow does not
        capture the WoW UI overlay at the character select screen.
        """
        # Try pixel bridge first — if it reads, we're in-world
        try:
            data = self._bridge.read()
            if data is not None:
                return "in_world"
        except Exception:
            pass

        # Check if WoW window exists (via process scan)
        hwnd = wow_process.get_wow_hwnd()
        if hwnd is None:
            return "no_window"

        # Capture full screen (ImageGrab captures UI overlays that PrintWindow misses)
        try:
            img = ImageGrab.grab()
        except Exception:
            return "unknown"

        # Sample character select probe points
        try:
            w, h = img.size
            matches = 0
            for rel_x, rel_y, expected_rgb in _CHARSELECT_PROBES:
                px = max(0, min(int(rel_x * w), w - 1))
                py = max(0, min(int(rel_y * h), h - 1))
                actual = img.getpixel((px, py))[:3]
                if _colour_match(actual, expected_rgb):
                    matches += 1
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
            state = self.detect_state()
            if state == target:
                return True
            if state == "no_window":
                logger.warning("_wait_for_state: WoW window disappeared")
                return False
            time.sleep(poll_interval)
        return False

    def _relative_to_screen(self, rel_x: float, rel_y: float) -> Tuple[int, int]:
        """Convert relative position to absolute screen coordinates for clicking.

        Uses logical window size from WowScreen (matches SetCursorPos coordinates).
        Adds small random offset for human-like behaviour.
        """
        # Refresh geometry
        self._screen._refresh_hwnd()
        self._screen._update_geometry()
        w, h = self._screen.client_size
        origin = self._screen.client_origin
        px = int(rel_x * w) + origin[0] + _rng.randint(-3, 3)
        py = int(rel_y * h) + origin[1] + _rng.randint(-3, 3)
        return (px, py)

    def login(self, slot: int = 1, timeout: int = 60) -> bool:
        """Log in from character select screen.

        Clicks the character slot, then "Enter World", and waits for
        the pixel bridge to confirm we're in-world.

        Args:
            slot: Character slot number (1-10, top to bottom).
            timeout: Maximum seconds to wait for login to complete.

        Returns:
            True if successfully entered world, False on timeout/failure.
        """
        start = time.monotonic()

        # Already in world?
        state = self.detect_state()
        if state == "in_world":
            logger.info("Login: already in-world")
            return True

        if state == "no_window":
            logger.error("Login: WoW window not found")
            return False

        # Wait for character select screen
        if state != "character_select":
            logger.info("Login: waiting for character select screen...")
            if not self._wait_for_state("character_select", timeout=10):
                logger.error("Login: character select screen not detected")
                return False

        remaining = timeout - (time.monotonic() - start)
        if remaining <= 0:
            return False

        # Bring WoW to foreground
        wow_process.set_foreground()

        # Click character slot (right-side panel)
        slot_y = _CHAR_LIST_TOP_Y + (slot - 1) * _CHAR_SLOT_SPACING
        slot_pos = self._relative_to_screen(_CHAR_LIST_X, slot_y)
        logger.info(f"Login: clicking slot {slot} at {slot_pos}")
        wow_process.left_click_at(slot_pos)
        time.sleep(_rng.uniform(0.3, 0.8))

        # Click "Enter World"
        enter_pos = self._relative_to_screen(_ENTER_WORLD_X, _ENTER_WORLD_Y)
        logger.info(f"Login: clicking Enter World at {enter_pos}")
        wow_process.left_click_at(enter_pos)
        time.sleep(_rng.uniform(0.5, 1.0))

        remaining = timeout - (time.monotonic() - start)
        if remaining <= 0:
            return False

        # Retry once if still on character select after 5s
        retry_deadline = time.monotonic() + min(5.0, remaining)
        while time.monotonic() < retry_deadline:
            state = self.detect_state()
            if state == "in_world":
                logger.info("Login: entered world successfully")
                time.sleep(2.0)  # settle delay for addon init
                return True
            if state != "character_select":
                break  # loading screen — proceed to main wait
            time.sleep(1.0)

        if state == "character_select":
            # Retry click sequence
            logger.info("Login: retrying click sequence")
            wow_process.set_foreground()
            slot_pos = self._relative_to_screen(_CHAR_LIST_X, slot_y)
            wow_process.left_click_at(slot_pos)
            time.sleep(_rng.uniform(0.3, 0.8))
            enter_pos = self._relative_to_screen(_ENTER_WORLD_X, _ENTER_WORLD_Y)
            wow_process.left_click_at(enter_pos)
            time.sleep(_rng.uniform(0.5, 1.0))

        # Wait for in-world
        remaining = timeout - (time.monotonic() - start)
        if remaining > 0 and self._wait_for_state("in_world", remaining):
            logger.info("Login: entered world successfully")
            time.sleep(2.0)  # settle delay for addon init
            return True

        elapsed = time.monotonic() - start
        logger.error(f"Login: timed out after {elapsed:.1f}s (limit {timeout}s)")
        return False

    def logout(self, timeout: int = 30) -> bool:
        """Log out from in-world to character select screen.

        Types /logout in chat and waits for the character select screen.

        Args:
            timeout: Maximum seconds to wait for logout to complete.

        Returns:
            True if reached character select, False on timeout/failure.
        """
        start = time.monotonic()

        state = self.detect_state()
        if state == "character_select":
            logger.info("Logout: already at character select")
            return True

        if state != "in_world":
            logger.error(f"Logout: expected in_world, got {state}")
            return False

        # Bring WoW to foreground
        wow_process.set_foreground()

        # Open chat and type /logout
        wow_process.press_key(0x0D)  # Enter — open chat
        time.sleep(_rng.uniform(0.1, 0.3))
        wow_process.type_text("/logout")
        time.sleep(_rng.uniform(0.05, 0.15))
        wow_process.press_key(0x0D)  # Enter — send command

        logger.info("Logout: sent /logout command")

        # Wait for character select
        remaining = timeout - (time.monotonic() - start)
        if remaining > 0 and self._wait_for_state("character_select", remaining):
            logger.info("Logout: reached character select")
            return True

        # Check if we're still in-world (logout may have been interrupted)
        state = self.detect_state()
        elapsed = time.monotonic() - start
        if state == "in_world":
            logger.warning(f"Logout: still in-world after {elapsed:.1f}s — may have been interrupted")
        else:
            logger.error(f"Logout: timed out in state '{state}' after {elapsed:.1f}s")

        return False
