# Auto Login/Logout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone `wow_login.py` module that automates WoW character select login and `/logout`, as a foundation for random breaks (#27) and auto-reconnect (#46).

**Architecture:** New `WowLogin` class that uses `WowScreen` for window capture/detection, `PixelBridge` for in-world detection, and `wow_process` for input. Screen state detected via pixel bridge (in-world) or relative-position colour sampling (character select). All coordinates are resolution-independent (relative to window size).

**Tech Stack:** Python, win32gui/win32api (SetForegroundWindow, mouse/keyboard), PIL (colour sampling), existing WowScreen/PixelBridge infrastructure.

**Spec:** `docs/superpowers/specs/2026-03-22-auto-login-logout-design.md`

---

### Task 1: Add helper functions to wow_process.py

**Files:**
- Modify: `wow_process.py:34-78`

Two new functions needed by the login/logout module.

- [ ] **Step 1: Add `set_foreground` function**

Add after line 59 (after `is_wow_classic`):

```python
def set_foreground():
    """Bring the WoW window to the foreground.

    Returns True if successful, False if WoW window not found or focus failed.
    """
    hwnd = get_wow_hwnd()
    if not hwnd:
        logger.warning("set_foreground: WoW window not found")
        return False
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        logger.warning(f"set_foreground failed: {e}")
        return False
    time.sleep(0.2)
    return True
```

- [ ] **Step 2: Add `type_text` function**

Add after `press_key` (after line 78):

```python
# Virtual key codes for characters used by type_text
_CHAR_TO_VK = {
    '/': 0xBF,  # VK_OEM_2
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45,
    'f': 0x46, 'g': 0x47, 'h': 0x48, 'i': 0x49, 'j': 0x4A,
    'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F,
    'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54,
    'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59,
    'z': 0x5A,
}


def type_text(text: str):
    """Type a string by sending individual key presses to WoW.

    Only supports lowercase a-z and '/'. Other characters are silently skipped.
    Used for sending slash commands like /logout.
    """
    for ch in text.lower():
        vk = _CHAR_TO_VK.get(ch)
        if vk:
            press_key(vk)
            time.sleep(_rng.uniform(0.03, 0.08))
```

- [ ] **Step 3: Verify no import changes needed**

`win32gui` and `time` are already imported in `wow_process.py`. No new imports required.

- [ ] **Step 4: Commit**

```bash
git add wow_process.py
git commit -m "feat: add set_foreground and type_text helpers to wow_process"
```

---

### Task 2: Add WowScreen.capture_full method

**Files:**
- Modify: `wow_screen.py:115-152`

The existing `get_bitmap` crops to centre half (for bobber search). The login module needs the full client area capture for colour sampling at arbitrary positions.

- [ ] **Step 1: Add `capture_full` method**

Add after `get_bitmap` (after line 152):

```python
def capture_full(self) -> Optional[Image.Image]:
    """Capture the full WoW client area without cropping.

    Returns an RGB PIL Image, or None if WoW window not found or capture fails.
    Also refreshes geometry (client_origin, client_size) as a side effect.
    """
    self._refresh_hwnd()
    if not self._hwnd:
        return None
    self._update_geometry()
    return self._print_window_capture()
```

- [ ] **Step 2: Add `client_origin` property**

Add after the `client_size` property (after line 197):

```python
@property
def client_origin(self) -> Tuple[int, int]:
    """Current WoW client area origin (x, y) in screen coordinates."""
    if self._client_origin == (0, 0):
        self._refresh_hwnd()
        self._update_geometry()
    return self._client_origin
```

- [ ] **Step 3: Verify imports**

Check line 4 — `Optional` and `Tuple` are already imported from `typing`. No change needed.

- [ ] **Step 3: Commit**

```bash
git add wow_screen.py
git commit -m "feat: add capture_full method to WowScreen"
```

---

### Task 3: Add character_slot config default

**Files:**
- Modify: `constants.py:15-39`

- [ ] **Step 1: Add `character_slot` to DEFAULT_CONFIG**

Add after `"compact_mode": False,` (line 38):

```python
    "character_slot": 1,
```

- [ ] **Step 2: Commit**

```bash
git add constants.py
git commit -m "feat: add character_slot config default"
```

---

### Task 4: Create wow_login.py — screen state detection

**Files:**
- Create: `wow_login.py`

This is the core of the module. Start with state detection, then add login/logout in subsequent tasks.

- [ ] **Step 1: Create wow_login.py with imports, constants, and WowLogin class**

```python
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
        self._screen.capture_full()
        w, h = self._screen.client_size
        origin = self._screen.client_origin
        px = int(rel_x * w) + origin[0] + _rng.randint(-3, 3)
        py = int(rel_y * h) + origin[1] + _rng.randint(-3, 3)
        return (px, py)
```

- [ ] **Step 2: Commit**

```bash
git add wow_login.py
git commit -m "feat: add wow_login.py with screen state detection"
```

---

### Task 5: Add login method

**Files:**
- Modify: `wow_login.py`

- [ ] **Step 1: Add `login` method to WowLogin class**

Add after `_relative_to_screen`:

```python
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

        # Click character slot
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

        logger.error(f"Login: timed out after {timeout}s")
        return False
```

- [ ] **Step 2: Commit**

```bash
git add wow_login.py
git commit -m "feat: add login method to WowLogin"
```

---

### Task 6: Add logout method

**Files:**
- Modify: `wow_login.py`

- [ ] **Step 1: Add `logout` method to WowLogin class**

Add after `login`:

```python
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
        if state == "in_world":
            logger.warning("Logout: still in-world — logout may have been interrupted")
        else:
            logger.error(f"Logout: timed out in state '{state}'")

        return False
```

- [ ] **Step 2: Commit**

```bash
git add wow_login.py
git commit -m "feat: add logout method to WowLogin"
```

---

### Task 7: Calibrate character select probe colours

**Files:**
- Modify: `wow_login.py` (update `_CHARSELECT_PROBES` constants)

This task requires running WoW and capturing screenshots at the character select screen.

- [ ] **Step 1: Write a calibration helper script**

Create `calibrate_charselect.py` (temporary, for measuring colours):

```python
"""Capture character select screen and print RGB values at probe positions.

Run this while WoW is on the character select screen.
Prints the RGB values at each probe position so they can be
copied into wow_login.py as _CHARSELECT_PROBES constants.
Also prints slot positions for validation.
"""

from wow_screen import WowScreen

screen = WowScreen()
img = screen.capture_full()
if img is None:
    print("ERROR: Could not capture WoW window")
    exit(1)

w, h = img.size
print(f"Window size: {w}x{h}")
print()

# Probe positions from wow_login.py
probes = [
    (0.50, 0.91, "Enter World button"),
    (0.25, 0.50, "Character list background"),
    (0.50, 0.96, "Bottom bar"),
]

print("=== Probe colours ===")
for rel_x, rel_y, label in probes:
    px, py = int(rel_x * w), int(rel_y * h)
    rgb = img.getpixel((px, py))[:3]
    print(f"  {label}: ({rel_x}, {rel_y}) -> pixel ({px}, {py}) -> RGB {rgb}")

print()
print("=== Character slot positions ===")
for slot in range(1, 11):
    rel_y = 0.35 + (slot - 1) * 0.055
    py = int(rel_y * h)
    px = int(0.50 * w)
    rgb = img.getpixel((px, py))[:3]
    print(f"  Slot {slot}: rel_y={rel_y:.3f} -> pixel ({px}, {py}) -> RGB {rgb}")

img.close()
print()
print("Update _CHARSELECT_PROBES in wow_login.py with the measured RGB values.")
print("Update _CHAR_LIST_TOP_Y and _CHAR_SLOT_SPACING if slot positions look off.")
```

- [ ] **Step 2: Run with WoW at character select**

```bash
cd /c/Users/perzi/laksefisk && python calibrate_charselect.py
```

Record the output. The RGB values and slot positions will tell us the correct constants.

- [ ] **Step 3: Update `_CHARSELECT_PROBES` in wow_login.py** *(requires human — values depend on calibration output)*

Replace the placeholder RGB values in `_CHARSELECT_PROBES` with measured values from the calibration output. Also update `_CHAR_LIST_TOP_Y` and `_CHAR_SLOT_SPACING` if the slot positions don't line up with actual character entries.

- [ ] **Step 4: Delete calibrate_charselect.py**

```bash
rm calibrate_charselect.py
```

- [ ] **Step 5: Commit**

```bash
git add wow_login.py
git commit -m "feat: calibrate character select detection colours from screenshots"
```

---

### Task 8: Manual testing

Test the complete module by running login and logout from a Python shell.

- [ ] **Step 1: Test detect_state**

With WoW at character select:
```python
from wow_screen import WowScreen
from pixel_bridge import PixelBridge
from wow_login import WowLogin

screen = WowScreen()
bridge = PixelBridge(screen)
login = WowLogin(screen, bridge)
print(login.detect_state())  # should print "character_select"
```

Log in manually, then:
```python
print(login.detect_state())  # should print "in_world"
```

- [ ] **Step 2: Test login**

Start at character select screen:
```python
result = login.login(slot=1)
print(result)  # should print True after entering world
```

- [ ] **Step 3: Test logout**

While in-world:
```python
result = login.logout()
print(result)  # should print True after reaching character select
```

- [ ] **Step 4: Test login with non-default slot**

If you have multiple characters, test selecting a different slot:
```python
result = login.login(slot=2)
print(result)
```

- [ ] **Step 5: Fix any issues found during testing**

Adjust probe colours, tolerances, slot positions, or timing as needed.

- [ ] **Step 6: Final commit (if any fixes were made)**

```bash
git add wow_login.py wow_process.py wow_screen.py constants.py
git commit -m "fix: adjust login/logout timing and detection from manual testing"
```
