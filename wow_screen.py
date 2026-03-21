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
        src_dc = None
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
            if src_dc:
                src_dc.DeleteDC()
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
        if self._client_size == (0, 0):
            self._refresh_hwnd()
            self._update_geometry()
        return self._client_size
