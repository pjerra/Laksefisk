# WoW-Only Window Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace mss screen-region capture with BitBlt from the WoW window client area, so overlapping windows and resolution changes don't break bobber detection or pixel bridge.

**Architecture:** `WowScreen` becomes an instance class using `GetDC(hwnd)` + `BitBlt` to capture the WoW client area. It caches the HWND (refreshed every 5s or on failure) and stores the client-to-screen origin for coordinate mapping. All callers receive a `WowScreen` instance instead of calling static methods.

**Tech Stack:** Python, pywin32 (`win32gui`, `win32ui`, `win32con`), PIL, ctypes (DPI awareness)

---

### Task 1: Make `_get_wow_hwnd()` public in `wow_process.py`

**Files:**
- Modify: `wow_process.py:41-59`

- [ ] **Step 1: Rename `_get_wow_hwnd` to `get_wow_hwnd`**

In `wow_process.py`, rename the function and update internal callers:

```python
# Line 41 — rename function
def get_wow_hwnd() -> Optional[int]:
    # ... body unchanged ...
```

- [ ] **Step 2: Update internal callers in `wow_process.py`**

Two internal callers use `_get_wow_hwnd()`:
- `press_key` (line 73): change to `get_wow_hwnd()`
- `right_click_mouse` (line 154): change to `get_wow_hwnd()`

- [ ] **Step 3: Verify no other files import `_get_wow_hwnd` directly**

Run: `grep -r "_get_wow_hwnd" C:/Users/perzi/laksefisk/ --include="*.py"`
Expected: only `wow_process.py` matches (the function is private, not imported elsewhere).

- [ ] **Step 4: Commit**

```bash
git add wow_process.py
git commit -m "refactor: make _get_wow_hwnd public for use by WowScreen"
```

---

### Task 2: Rewrite `WowScreen` to use BitBlt window capture

**Files:**
- Modify: `wow_screen.py` (full rewrite)

- [ ] **Step 1: Rewrite `wow_screen.py` with BitBlt capture**

Replace the entire file with:

```python
import ctypes
import logging
import time
from typing import Optional, Tuple

import win32con
import win32gui
import win32ui
from PIL import Image

from wow_process import get_wow_hwnd

logger = logging.getLogger("Laksefisk")

# Cache refresh interval (seconds)
_HWND_CACHE_TTL = 5.0


class WowScreen:
    """Captures the WoW window client area via BitBlt."""

    def __init__(self):
        self._hwnd: Optional[int] = None
        self._hwnd_time: float = 0.0
        self._client_origin: Tuple[int, int] = (0, 0)
        self._client_size: Tuple[int, int] = (0, 0)

    def _refresh_hwnd(self, force: bool = False):
        """Refresh cached HWND if stale or forced."""
        now = time.monotonic()
        if not force and self._hwnd and (now - self._hwnd_time) < _HWND_CACHE_TTL:
            return
        hwnd = get_wow_hwnd()
        if hwnd:
            self._hwnd = hwnd
            self._hwnd_time = now
        else:
            self._hwnd = None

    def _update_geometry(self):
        """Update client area origin and size from current HWND."""
        if not self._hwnd:
            return
        try:
            # Client area origin in screen coords
            pt = win32gui.ClientToScreen(self._hwnd, (0, 0))
            self._client_origin = pt
            # Client area size
            rect = win32gui.GetClientRect(self._hwnd)
            self._client_size = (rect[2], rect[3])
        except Exception:
            self._hwnd = None

    def _bitblt_capture(self, x: int, y: int, w: int, h: int) -> Optional[Image.Image]:
        """Capture a region of the WoW client area via BitBlt.

        x, y are relative to the client area top-left.
        Returns an RGB PIL Image, or None on failure.
        """
        if not self._hwnd:
            return None

        hwnd = self._hwnd  # capture before exception handler may clear it
        wnd_dc = None
        save_dc = None
        bmp = None
        try:
            wnd_dc = win32gui.GetDC(hwnd)
            src_dc = win32ui.CreateDCFromHandle(wnd_dc)
            save_dc = src_dc.CreateCompatibleDC()

            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(src_dc, w, h)
            save_dc.SelectObject(bmp)

            save_dc.BitBlt((0, 0), (w, h), src_dc, (x, y), win32con.SRCCOPY)

            bmp_info = bmp.GetInfo()
            bmp_bits = bmp.GetBitmapBits(True)

            img = Image.frombuffer(
                "RGB",
                (bmp_info["bmWidth"], bmp_info["bmHeight"]),
                bmp_bits,
                "raw",
                "BGRX",
                0,
                1,
            )
            return img
        except Exception as e:
            logger.warning(f"BitBlt capture failed: {e}")
            self._hwnd = None
            return None
        finally:
            if save_dc:
                save_dc.DeleteDC()
            if bmp:
                win32gui.DeleteObject(bmp.GetHandle())
            if wnd_dc and hwnd:
                win32gui.ReleaseDC(hwnd, wnd_dc)

    def get_bitmap(self) -> Image.Image:
        """Capture the entire WoW client area.

        Returns an RGB PIL Image.
        Raises RuntimeError if WoW window not found or capture fails.
        """
        self._refresh_hwnd()
        if not self._hwnd:
            raise RuntimeError("WoW window not found")

        self._update_geometry()
        w, h = self._client_size
        if w <= 0 or h <= 0:
            raise RuntimeError("WoW client area has zero size (window minimized?)")

        img = self._bitblt_capture(0, 0, w, h)
        if img is None:
            # Force HWND refresh and retry once
            self._refresh_hwnd(force=True)
            if not self._hwnd:
                raise RuntimeError("WoW window not found after refresh")
            self._update_geometry()
            w, h = self._client_size
            img = self._bitblt_capture(0, 0, w, h)
            if img is None:
                raise RuntimeError("BitBlt capture failed")

        return img

    def get_region(self, x: int, y: int, w: int, h: int) -> Image.Image:
        """Capture a sub-region of the WoW client area.

        x, y, w, h are in client-area pixel coordinates.
        Raises RuntimeError if WoW window not found or capture fails.
        """
        self._refresh_hwnd()
        if not self._hwnd:
            raise RuntimeError("WoW window not found")

        self._update_geometry()

        img = self._bitblt_capture(x, y, w, h)
        if img is None:
            raise RuntimeError("BitBlt region capture failed")

        return img

    @staticmethod
    def get_color_at(pos: Tuple[int, int], bmp: Image.Image) -> Tuple[int, int, int]:
        return bmp.getpixel(pos)[:3]

    def get_screen_position_from_bitmap_position(self, pos: Tuple[int, int]) -> Tuple[int, int]:
        """Convert bitmap (client-area) position to screen position."""
        return (pos[0] + self._client_origin[0], pos[1] + self._client_origin[1])

    @property
    def client_size(self) -> Tuple[int, int]:
        """Current WoW client area size (width, height)."""
        return self._client_size
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('wow_screen.py', doraise=True)"`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add wow_screen.py
git commit -m "feat: rewrite WowScreen to use BitBlt window capture

Replaces mss screen-region capture with BitBlt from WoW client DC.
Captures WoW content regardless of overlapping windows.
HWND cached with 5s TTL, coordinate mapping via ClientToScreen."
```

---

### Task 3: Add DPI awareness setup without mss

**Files:**
- Modify: `gui.py:83-90`

- [ ] **Step 1: Replace mss DPI warm-up with direct ctypes call**

In `gui.py`, replace lines 86-90:

```python
        # OLD:
        # mss DPI warm-up — MUST be before any geometry calls.
        # mss.mss() changes Windows DPI awareness on first call, which would
        # resize the tkinter window if called later.
        with mss.mss():
            pass
```

With:

```python
        # DPI awareness — MUST be before any geometry calls.
        # Without this, GetClientRect/ClientToScreen return wrong values on
        # high-DPI displays, and the tkinter window may resize unexpectedly.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        except (AttributeError, OSError):
            pass  # shcore not available on older Windows
```

- [ ] **Step 2: Remove `import mss` from `gui.py`**

Remove line 23: `import mss`

Check that no other code in `gui.py` uses `mss`. Run:
`grep -n "mss" gui.py`
Expected: no remaining references.

- [ ] **Step 3: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('gui.py', doraise=True)"`

- [ ] **Step 4: Commit**

```bash
git add gui.py
git commit -m "refactor: replace mss DPI warm-up with direct ctypes call"
```

---

### Task 4: Update `bobber_finder.py` to use WowScreen instance

**Files:**
- Modify: `bobber_finder.py`

- [ ] **Step 1: Change `SearchBobberFinder.__init__` to accept WowScreen instance**

```python
# Line 36-37, change:
class SearchBobberFinder(IBobberFinder):
    def __init__(self, pixel_classifier: PixelClassifier, wow_screen: 'WowScreen'):
        self.pixel_classifier = pixel_classifier
        self._wow_screen = wow_screen
        # ... rest unchanged ...
```

- [ ] **Step 2: Replace all `WowScreen.get_bitmap()` with `self._wow_screen.get_bitmap()`**

Three locations in `SearchBobberFinder`:
- Line 60: `self._bitmap = self._wow_screen.get_bitmap()`
- Line 90: `return self._wow_screen.get_screen_position_from_bitmap_position(self._previous_location)`
- Line 98: `return self._wow_screen.get_screen_position_from_bitmap_position(raw_bitmap)`

- [ ] **Step 3: Update `BobberColourPointFinder` similarly**

```python
class BobberColourPointFinder(IBobberFinder):
    TARGET_OFFSET = 15

    def __init__(self, target_color: Tuple[int, int, int], wow_screen: 'WowScreen'):
        self.target_color = target_color
        self._wow_screen = wow_screen
        # ... rest unchanged ...
```

Replace static calls:
- Line 201: `self._bitmap = self._wow_screen.get_bitmap()`
- Line 220: `return self._wow_screen.get_screen_position_from_bitmap_position((x, y))`

- [ ] **Step 4: Keep the `from wow_screen import WowScreen` import** (needed for type hint)

- [ ] **Step 5: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('bobber_finder.py', doraise=True)"`

- [ ] **Step 6: Commit**

```bash
git add bobber_finder.py
git commit -m "refactor: bobber_finder uses WowScreen instance instead of static calls"
```

---

### Task 5: Update `bobber_calibration.py` to use WowScreen instance

**Files:**
- Modify: `bobber_calibration.py`

- [ ] **Step 1: Add `wow_screen` parameter to `sweep_calibrate` and `calibrate_now`**

```python
# Line 116
def sweep_calibrate(pixel_classifier: PixelClassifier, wow_screen: 'WowScreen') -> bool:
```

```python
# Line 205
def calibrate_now(pixel_classifier: PixelClassifier, wow_screen: 'WowScreen') -> Optional[dict]:
    success = sweep_calibrate(pixel_classifier, wow_screen)
```

- [ ] **Step 2: Replace `WowScreen.get_bitmap()` call**

Line 131: change `img = WowScreen.get_bitmap()` to `img = wow_screen.get_bitmap()`

- [ ] **Step 3: Keep the import** (needed for type hint)

- [ ] **Step 4: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('bobber_calibration.py', doraise=True)"`

- [ ] **Step 5: Commit**

```bash
git add bobber_calibration.py
git commit -m "refactor: bobber_calibration uses WowScreen instance parameter"
```

---

### Task 6: Update `pixel_bridge.py` to use WowScreen instance

**Files:**
- Modify: `pixel_bridge.py`

- [ ] **Step 1: Change `__init__` to accept WowScreen instance**

```python
# Line 174
def __init__(self, wow_screen: 'WowScreen', scan_region: Optional[dict] = None):
    self._wow_screen = wow_screen
    self._item_lookup: dict = {}
    self._cached_region: Optional[dict] = None
    self._scan_region: Optional[dict] = scan_region
    self._cache_miss: int = 0
    self._last_data: Optional[PixelBridgeData] = None
    self._connected: bool = False
    self._consecutive_failures: int = 0
    # Remove self._screen_w / self._screen_h — no longer needed

    # Load item lookup (unchanged)
    lookup_path = os.path.join(os.path.dirname(__file__), "item_lookup.json")
    # ... rest unchanged ...
```

- [ ] **Step 2: Replace `_capture_bottom_strip` with WoW-window-relative capture**

```python
def _capture_bottom_strip(self):
    """Capture the bottom 250px of the WoW client area."""
    cw, ch = self._wow_screen.client_size
    y_start = max(0, ch - SCAN_HEIGHT)
    h = ch - y_start
    img = self._wow_screen.get_region(0, y_start, cw, h)
    region = {"left": 0, "top": y_start, "width": cw, "height": h}
    return img, region
```

- [ ] **Step 3: Replace `_capture_region` with WowScreen-based capture**

```python
def _capture_region(self, region):
    """Capture a region relative to the WoW client area."""
    return self._wow_screen.get_region(
        region["left"], region["top"],
        region["width"], region["height"],
    )
```

- [ ] **Step 4: Remove `import mss`**

Remove line 25: `import mss`
Keep `from PIL import Image` — it is used in `_find_pixel_bar` and `_read_pixel`.

- [ ] **Step 5: Remove `self._screen_w`, `self._screen_h`, and the mss block in `__init__`**

Remove lines 186-189 (the `with mss.mss() as sct:` block that populated `_screen_w`/`_screen_h`).
Remove `self._screen_w` and `self._screen_h` instance variables — they are replaced by `self._wow_screen.client_size`.

- [ ] **Step 6: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('pixel_bridge.py', doraise=True)"`

- [ ] **Step 7: Commit**

```bash
git add pixel_bridge.py
git commit -m "feat: pixel_bridge captures from WoW window instead of screen

Uses WowScreen.get_region() for both fast-path cached captures and
slow-path bottom-strip scanning. Fixes _capture_bottom_strip to
actually capture only bottom 250px instead of full screen."
```

---

### Task 7: Update `settings.py` to use WowScreen instance

**Files:**
- Modify: `settings.py`

`SettingsPopup` already stores a reference to `App` as `self._parent` (line 45). Since `App` will have `self._wow_screen` (wired in Task 8), access it via `self._parent._wow_screen` — no constructor change needed.

- [ ] **Step 1: Replace static call at line 369**

Change `img = WowScreen.get_bitmap()` to `img = self._parent._wow_screen.get_bitmap()`

- [ ] **Step 2: Remove `from wow_screen import WowScreen` import** (line 28)

No longer needed since we access via parent.

- [ ] **Step 3: Verify syntax**

Run: `python -c "import py_compile; py_compile.compile('settings.py', doraise=True)"`

- [ ] **Step 4: Commit**

```bash
git add settings.py
git commit -m "refactor: settings uses WowScreen instance for colour preview"
```

---

### Task 8: Wire everything together in `gui.py` and `fishing_bot.py`

**Files:**
- Modify: `gui.py`
- Modify: `fishing_bot.py`

- [ ] **Step 1: Create WowScreen instance in `App.__init__`**

After the DPI awareness call (from Task 3), add:

```python
        # Screen capture
        self._wow_screen = WowScreen()
```

Note: `import ctypes` already exists in gui.py (line 9), no new import needed for DPI.

- [ ] **Step 2: Pass WowScreen to SearchBobberFinder**

Line 112: change `SearchBobberFinder(self._pc)` to `SearchBobberFinder(self._pc, self._wow_screen)`

- [ ] **Step 3: Pass WowScreen to PixelBridge**

Find where `PixelBridge()` is created in gui.py and change to `PixelBridge(self._wow_screen)`

- [ ] **Step 4: Update `_on_calibrate` in gui.py (line 599)**

Change `sweep_calibrate(self._pc)` to `sweep_calibrate(self._pc, self._wow_screen)`

- [ ] **Step 5: Add `wow_screen` parameter to `LaksefiskBot.__init__`**

In `fishing_bot.py`, add parameter to constructor:

```python
class LaksefiskBot:
    def __init__(
        self,
        bobber_finder: IBobberFinder,
        bite_watcher: IBiteWatcher,
        cast_key: int,
        wow_screen=None,
        lure_key: Optional[int] = None,
        loot_wait_min: float = LOOT_WAIT_MIN,
        loot_wait_max: float = LOOT_WAIT_MAX,
    ):
        # ... existing assignments ...
        self._wow_screen = wow_screen
```

- [ ] **Step 6: Update `sweep_calibrate` call in `fishing_bot.py` (line 88)**

Change `if sweep_calibrate(self._pixel_classifier):` to `if sweep_calibrate(self._pixel_classifier, self._wow_screen):`

- [ ] **Step 7: Pass WowScreen to LaksefiskBot in gui.py (line 615)**

Change the `LaksefiskBot(...)` creation to include `wow_screen=self._wow_screen`:

```python
        self._bot = LaksefiskBot(
            bobber_finder=self._bobber_finder,
            bite_watcher=self._bite_watcher,
            cast_key=self._cast_key,
            wow_screen=self._wow_screen,
            lure_key=self._lure_key,
            loot_wait_min=self._loot_min,
            loot_wait_max=self._loot_max,
        )
```

- [ ] **Step 8: SettingsPopup — no change needed**

`SettingsPopup` accesses `self._parent._wow_screen` (handled in Task 7).

- [ ] **Step 9: Verify syntax**

Run:
```bash
python -c "import py_compile; py_compile.compile('gui.py', doraise=True)"
python -c "import py_compile; py_compile.compile('fishing_bot.py', doraise=True)"
```

- [ ] **Step 10: Commit**

```bash
git add gui.py fishing_bot.py
git commit -m "feat: wire WowScreen instance to all components

Creates WowScreen in App.__init__ and passes to bobber_finder,
pixel_bridge, fishing_bot, and calibration."
```

---

### Task 9: Update test files

**Files:**
- Modify: `tests/test_search_area.py`
- Modify: `tests/test_pixel_reader.py`
- Modify: `tests/test_fit_preview.py`
- Modify: `tests/test_search_area_v1.py`
- Modify: `tests/test_search_area_v2.py`
- Modify: `tests/test_bobber_calibration.py`
- Evaluate: `tests/test_ocr_chat.py` (may import mss)

- [ ] **Step 1: Update each test file that uses `WowScreen.get_bitmap()` statically**

For each file, create a `WowScreen()` instance and use it instead of static calls:

```python
from wow_screen import WowScreen
ws = WowScreen()
# Replace WowScreen.get_bitmap() → ws.get_bitmap()
# Replace WowScreen.get_screen_position_from_bitmap_position(...) → ws.get_screen_position_from_bitmap_position(...)
```

- [ ] **Step 2: Update test files that use their own mss capture**

`test_pixel_reader.py` has its own mss-based capture. Replace with `WowScreen` instance calls:
- Use `ws.get_region(...)` for sub-region captures
- Use `ws.get_bitmap()` for full captures

- [ ] **Step 3: Remove `import mss` from test files that no longer need it**

- [ ] **Step 4: Verify syntax for all modified test files**

Run for each:
```bash
python -c "import py_compile; py_compile.compile('tests/test_search_area.py', doraise=True)"
```

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "refactor: update test tools to use WowScreen instance"
```

---

### Task 10: Remove mss dependency if no longer used

**Files:**
- Possibly modify: `requirements.txt` or equivalent

- [ ] **Step 1: Check for remaining mss usage**

Run: `grep -r "import mss" C:/Users/perzi/laksefisk/ --include="*.py"`

If no files import mss, it can be removed from dependencies.

- [ ] **Step 2: If mss is unused, remove from requirements**

Check if there's a `requirements.txt`:
```bash
ls requirements.txt setup.py pyproject.toml
```

Remove `mss` from whichever dependency file exists.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt  # or equivalent
git commit -m "chore: remove mss dependency (replaced by BitBlt capture)"
```

---

### Task 11: Manual smoke test

- [ ] **Step 1: Launch the bot**

```bash
cd C:/Users/perzi/laksefisk
python gui.py
```

Expected: GUI opens without errors.

- [ ] **Step 2: With WoW open in windowed mode, click Start**

Verify:
- Bobber is detected (preview shows highlighted feather pixels)
- Pixel bridge connects (status shows addon data)
- Calibration runs successfully on first cast

- [ ] **Step 3: Test overlapping window**

While fishing, briefly cover part of the WoW window with another application window. Verify the bot continues detecting the bobber without interruption.

- [ ] **Step 4: Test settings preview**

Open Settings → check that the colour preview captures from WoW correctly.

- [ ] **Step 5: Test pixel bar reader**

Run `python tests/test_pixel_reader.py` — verify it finds and reads the pixel bar.
