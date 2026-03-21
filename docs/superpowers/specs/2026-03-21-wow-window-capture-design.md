# Task #48: WoW-Only Window Capture

## Problem

The bot currently captures a fixed region from the center of the screen using `mss`. This breaks when:
- A notification or window overlaps WoW
- WoW is not centered on the primary monitor
- Resolution changes (e.g. remote connect)

## Solution

Replace screen-region capture with BitBlt from the WoW window client area. This captures WoW's rendered content regardless of overlapping windows.

## Approach: BitBlt from Client DC

Use `GetDC(hwnd)` (client area only, excludes title bar/borders) + `BitBlt` to capture the WoW window by handle. WoW runs in windowed or borderless-windowed mode.

## Design

### 1. WowScreen Changes

**Static → instance-based:** `WowScreen` currently uses `@staticmethod` methods. Convert to an instance class that stores the HWND and client-area origin between calls. All callers (`bobber_finder.py`, `bobber_calibration.py`, etc.) switch from `WowScreen.get_bitmap()` to using an instance.

**HWND caching:** Cache the WoW HWND and refresh every ~5 seconds (or on capture failure). The current `_get_wow_hwnd()` iterates all processes + windows — too expensive per-frame. Make `_get_wow_hwnd()` public as `get_wow_hwnd()` since `wow_screen.py` now depends on it.

Replace `get_bitmap()`:

1. Use cached HWND (refresh periodically or on failure)
2. `GetClientRect(hwnd)` for bitmap dimensions
3. `GetDC(hwnd)` → `CreateCompatibleDC` → `CreateCompatibleBitmap` → `BitBlt` → extract pixel data
4. Cleanup: `DeleteObject(bitmap)`, `DeleteDC(compatible_dc)`, `ReleaseDC(hwnd, dc)` in try/finally
5. Convert to `PIL.Image` (RGB), return as before

Add `get_region(x, y, w, h)` for sub-region captures within the WoW client area. Used by pixel bridge for both fast-path (cached bar region) and slow-path (bottom strip scan) captures.

Remove the old mss-based center-of-screen capture.

### 2. Coordinate Mapping

- After each capture, use `ClientToScreen(hwnd, (0, 0))` to get the client area's screen-space origin
- Store this origin for `get_screen_position_from_bitmap_position(pos)` which adds the origin offset
- This correctly maps bitmap coords → screen coords for mouse clicks, regardless of window borders/title bar
- Origin is re-queried every capture, so window moves are handled automatically

### 3. Pixel Bridge Impact

Both pixel bridge capture paths switch to WoW-window-relative capture via `WowScreen.get_region()`:

- **Slow scan:** Currently captures the full screen (despite `SCAN_HEIGHT = 250` constant existing). Fix this: capture only the bottom 250px of the WoW client area
- **Fast path:** Cached small region, coordinates relative to WoW client area

Pixel bridge stored coordinates become window-relative, surviving window moves.

### 4. Callers

**API change (static → instance):**
- `bobber_finder.py` — receives `WowScreen` instance, calls `instance.get_bitmap()`
- `bobber_calibration.py` — receives `WowScreen` instance
- `fishing_bot.py` — uses bobber finder, no direct capture calls
- `gui.py` — creates `WowScreen` instance, passes to bobber finder and pixel bridge

**Minor updates:**
- `tests/test_pixel_reader.py` — switch from own mss capture to `WowScreen`
- `tests/test_search_area.py` — switch from own capture to `WowScreen`

**Evaluate for mss usage (may need updates):**
- `tests/test_bobber_calibration.py`
- `tests/test_fit_preview.py`
- `tests/test_search_area_v1.py`, `test_search_area_v2.py`
- `tests/test_ocr_chat.py`

### 5. Error Handling

- WoW window not found: log warning and raise exception. Bot's existing retry/stop logic handles it
- BitBlt fails (window minimized): same treatment — bot already handles capture failures
- GDI resource cleanup via try/finally on every capture to prevent leaks

### 6. DPI Awareness

- Keep the `SetProcessDpiAwareness` call (currently in mss warm-up) for correct `GetWindowRect`/`ClientToScreen` results
- Move it out of mss context if mss is removed
- Evaluate removing `mss` dependency if nothing else uses it

## Files Modified

- `wow_screen.py` — Core capture rewrite (BitBlt + client DC + instance-based)
- `wow_process.py` — Make `_get_wow_hwnd()` public
- `pixel_bridge.py` — Switch to window-relative captures via `WowScreen.get_region()`
- `bobber_finder.py` — Use `WowScreen` instance instead of static calls
- `bobber_calibration.py` — Use `WowScreen` instance
- `gui.py` — Create `WowScreen` instance, pass to components, move DPI setup
- `tests/test_pixel_reader.py` — Use `WowScreen` instead of own mss capture
- `tests/test_search_area.py` — Use `WowScreen` instead of own capture
- Other test files — evaluate for mss usage

## Constraints

- WoW must be open and visible (not minimized) for BitBlt to work
- WoW must be focused for mouse/key input (unchanged requirement)
- Windowed or borderless-windowed mode only (no fullscreen exclusive)
