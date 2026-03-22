import ctypes
import logging
import math
import random
import time
from typing import List, Optional, Tuple

import psutil
import win32api
import win32con
import win32gui
import win32process

logger = logging.getLogger("Laksefisk")

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_LBUTTONDOWN = 0x201
WM_LBUTTONUP = 0x202
WM_RBUTTONDOWN = 0x204
WM_RBUTTONUP = 0x205
VK_RMB = 0x02

LOOT_DELAY = 2000  # ms

_last_key: int = 0
_rng = random.Random()

MOUSEEVENTF_LEFTDOWN = 0x00000002
MOUSEEVENTF_LEFTUP = 0x00000004
MOUSEEVENTF_RIGHTDOWN = 0x00000008
MOUSEEVENTF_RIGHTUP = 0x00000010

user32 = ctypes.windll.user32


def _mouse_event(flags: int, x: int, y: int):
    user32.mouse_event(flags, x, y, 0, 0)


def get_wow_hwnd() -> Optional[int]:
    names = {"wow", "wowclassic", "wow-64"}
    for proc in psutil.process_iter(["pid", "name"]):
        pname = proc.info["name"]
        if not pname:
            continue
        if pname.lower().rstrip(".exe") in names or pname.lower().replace(".exe", "") in names:
            hwnds = []

            def callback(hwnd, extra):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == proc.info["pid"] and win32gui.IsWindowVisible(hwnd):
                    hwnds.append(hwnd)

            win32gui.EnumWindows(callback, None)
            if hwnds:
                return hwnds[0]
    logger.error("Failed to find the WoW process (Wow, WowClassic, Wow-64)")
    return None


def is_wow_classic() -> bool:
    for proc in psutil.process_iter(["name"]):
        pname = proc.info["name"]
        if pname and "classic" in pname.lower():
            return True
    return False


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


def press_key(vk_code: int):
    global _last_key
    _last_key = vk_code
    hwnd = get_wow_hwnd()
    if hwnd:
        win32api.PostMessage(hwnd, WM_KEYDOWN, vk_code, 0)
        time.sleep((50 + _rng.randint(0, 75)) / 1000)
        win32api.PostMessage(hwnd, WM_KEYUP, vk_code, 0)


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


# ---------------------------------------------------------------------------
# Human-like mouse movement using a Bezier curve with random control points
# ---------------------------------------------------------------------------

def _bezier_point(t: float, p0: Tuple[float, float], p1: Tuple[float, float],
                  p2: Tuple[float, float], p3: Tuple[float, float]) -> Tuple[float, float]:
    """Cubic Bezier interpolation at parameter t (0..1)."""
    u = 1 - t
    x = u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0]
    y = u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]
    return (x, y)


def _human_move_mouse(start: Tuple[int, int], end: Tuple[int, int]):
    """Move cursor from start to end along a curved path with variable speed."""
    sx, sy = float(start[0]), float(start[1])
    ex, ey = float(end[0]), float(end[1])

    dist = math.hypot(ex - sx, ey - sy)
    if dist < 5:
        win32api.SetCursorPos((int(ex), int(ey)))
        return

    # Two random control points that curve the path slightly
    # Offset perpendicular to the line by a random amount (max ±30% of distance)
    dx, dy = ex - sx, ey - sy
    perp_x, perp_y = -dy, dx  # perpendicular vector
    length = math.hypot(perp_x, perp_y)
    if length > 0:
        perp_x /= length
        perp_y /= length

    offset1 = _rng.uniform(-0.3, 0.3) * dist
    offset2 = _rng.uniform(-0.3, 0.3) * dist

    cp1 = (sx + dx * 0.3 + perp_x * offset1, sy + dy * 0.3 + perp_y * offset1)
    cp2 = (sx + dx * 0.7 + perp_x * offset2, sy + dy * 0.7 + perp_y * offset2)

    # Number of steps: more for longer distances, minimum 15
    steps = max(15, int(dist / 8))

    for i in range(steps + 1):
        t = i / steps

        # Ease in/out — move slower at start and end (like a human)
        t_eased = t * t * (3 - 2 * t)  # smoothstep

        bx, by = _bezier_point(t_eased, (sx, sy), cp1, cp2, (ex, ey))

        # Add tiny random jitter (±1 pixel) for realism
        jx = bx + _rng.uniform(-1, 1)
        jy = by + _rng.uniform(-1, 1)

        win32api.SetCursorPos((int(jx), int(jy)))

        # Variable delay: slower at start/end, faster in middle
        base_delay = 0.005 + 0.008 * (1 - 4 * (t - 0.5) ** 2)
        time.sleep(base_delay + _rng.uniform(0, 0.003))

    # Ensure we land exactly on target
    win32api.SetCursorPos((int(ex), int(ey)))


def left_click_at(position: Tuple[int, int]):
    """Left-click at position to trigger delete popup."""
    win32api.SetCursorPos(position)
    time.sleep(0.05 + _rng.uniform(0, 0.05))
    _mouse_event(MOUSEEVENTF_LEFTDOWN, position[0], position[1])
    time.sleep((30 + _rng.randint(0, 47)) / 1000)
    _mouse_event(MOUSEEVENTF_LEFTUP, position[0], position[1])


def right_click_mouse(position: Tuple[int, int]):
    """Move mouse to position with human-like movement, then right-click."""
    hwnd = get_wow_hwnd()
    if hwnd is None:
        return

    old_pos = win32api.GetCursorPos()

    # Human-like movement to the bobber
    _human_move_mouse(old_pos, position)

    # Small pause after arriving (like a human settling on target)
    time.sleep(0.05 + _rng.uniform(0, 0.1))

    # Right-click
    _mouse_event(MOUSEEVENTF_RIGHTDOWN, position[0], position[1])
    time.sleep((30 + _rng.randint(0, 47)) / 1000)
    _mouse_event(MOUSEEVENTF_RIGHTUP, position[0], position[1])
