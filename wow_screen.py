import ctypes
import logging
import time
from typing import Optional, Tuple

import win32gui
import win32ui
from PIL import Image

from wow_process import get_wow_hwnd

logger = logging.getLogger("Laksefisk")

# Cache refresh interval (seconds)
_HWND_CACHE_TTL = 5.0

# PrintWindow flags
_PW_CLIENTONLY = 0x00000001
_PW_RENDERFULLCONTENT = 0x00000002

_user32 = ctypes.windll.user32


class WowScreen:
    """Captures the WoW window client area via PrintWindow."""

    def __init__(self):
        self._hwnd: Optional[int] = None
        self._hwnd_time: float = 0.0
        self._client_origin: Tuple[int, int] = (0, 0)
        self._client_size: Tuple[int, int] = (0, 0)
        self._crop_offset: Tuple[int, int] = (0, 0)

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
            pt = win32gui.ClientToScreen(self._hwnd, (0, 0))
            self._client_origin = pt
            rect = win32gui.GetClientRect(self._hwnd)
            self._client_size = (rect[2], rect[3])
        except Exception:
            self._hwnd = None

    def _print_window_capture(self) -> Optional[Image.Image]:
        """Capture the WoW client area via PrintWindow.

        Uses PW_RENDERFULLCONTENT to capture DirectX-rendered content.
        Returns an RGB PIL Image, or None on failure.
        """
        if not self._hwnd:
            return None

        hwnd = self._hwnd
        w, h = self._client_size
        if w <= 0 or h <= 0:
            return None

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

            result = _user32.PrintWindow(hwnd, save_dc.GetSafeHdc(),
                                         _PW_RENDERFULLCONTENT | _PW_CLIENTONLY)
            if not result:
                logger.warning("PrintWindow returned 0 (failed)")
                return None

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
            logger.warning(f"PrintWindow capture failed: {e}")
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
        """Capture the centre portion of the WoW client area for bobber search.

        Crops to the centre half (same region as the original mss capture)
        to avoid false positives from UI elements at the edges.
        Returns an RGB PIL Image.
        Raises RuntimeError if WoW window not found or capture fails.
        """
        self._refresh_hwnd()
        if not self._hwnd:
            raise RuntimeError("WoW window not found")

        self._update_geometry()

        img = self._print_window_capture()
        if img is None:
            # Force HWND refresh and retry once
            self._refresh_hwnd(force=True)
            if not self._hwnd:
                raise RuntimeError("WoW window not found after refresh")
            self._update_geometry()
            img = self._print_window_capture()
            if img is None:
                raise RuntimeError("PrintWindow capture failed")

        # Crop to centre half (matching original mss region)
        w, h = self._client_size
        left = w // 4
        top = h // 4
        right = left + w // 2
        bottom = top + h // 2 - 100
        cropped = img.crop((left, top, right, bottom))
        img.close()

        # Store crop offset for coordinate mapping
        self._crop_offset = (left, top)

        return cropped

    def get_region(self, x: int, y: int, w: int, h: int) -> Image.Image:
        """Capture a sub-region of the WoW client area.

        Captures the full client area via PrintWindow, then crops.
        x, y, w, h are in client-area pixel coordinates.
        Raises RuntimeError if WoW window not found or capture fails.
        """
        self._refresh_hwnd()
        if not self._hwnd:
            raise RuntimeError("WoW window not found")

        self._update_geometry()

        img = self._print_window_capture()
        if img is None:
            raise RuntimeError("PrintWindow region capture failed")

        # Crop to requested region
        cropped = img.crop((x, y, x + w, y + h))
        img.close()
        return cropped

    @staticmethod
    def get_color_at(pos: Tuple[int, int], bmp: Image.Image) -> Tuple[int, int, int]:
        return bmp.getpixel(pos)[:3]

    def get_screen_position_from_bitmap_position(self, pos: Tuple[int, int]) -> Tuple[int, int]:
        """Convert bitmap position to screen position.

        Accounts for both the crop offset (centre region within client area)
        and the client area origin (client area within screen).
        """
        return (
            pos[0] + self._crop_offset[0] + self._client_origin[0],
            pos[1] + self._crop_offset[1] + self._client_origin[1],
        )

    @property
    def client_size(self) -> Tuple[int, int]:
        """Current WoW client area size (width, height)."""
        if self._client_size == (0, 0):
            self._refresh_hwnd()
            self._update_geometry()
        return self._client_size
