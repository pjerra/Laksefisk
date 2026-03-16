"""
Pixel bridge reader — reads Laksefisk addon pixel data from the WoW screen.

Auto-scans the bottom of the screen for the magenta→cyan sync pattern.
Caches the position for fast subsequent reads.

Pixel layout (must match Laksefisk.lua v8):
  [0]  Sync 1 — magenta    [1]  Sync 2 — cyan
  [2]  Status: alive/combat/fishing
  [3]  Counters: loot_parity / bags_full / cast_parity
  [4]  Chat: whisper/say/yell parity
  [5-7]  Catch count (8-bit binary, MSB first) — pixel 7 B = player nearby
  [8-13]  Item ID (18-bit binary, MSB first)
  [14-16] Bait time remaining (seconds/5, 8-bit binary)
  [17-19] Player HP percent (8-bit binary)
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import mss
from PIL import Image

logger = logging.getLogger("Laksefisk")

# Must match Laksefisk.lua v8
NUM_PIXELS = 20
ITEM_ID_START = 8
ITEM_ID_PIXELS = 6
BAIT_START = 14
HP_START = 17

# Sync colours
SYNC1 = (255, 0, 255)  # magenta
SYNC2 = (0, 255, 255)  # cyan
COLOUR_TOLERANCE = 20

# How much of the screen bottom to scan (pixels from bottom edge)
SCAN_HEIGHT = 250


@dataclass
class PixelBridgeData:
    """Decoded pixel bridge state."""
    alive: bool = True
    combat: bool = False
    fishing: bool = False
    loot_parity: int = 0
    bags_full: bool = False
    cast_parity: int = 0
    catch_count: int = 0
    player_nearby: bool = False
    item_id: int = 0
    item_name: str = ""
    bait_seconds: int = 0
    hp_percent: int = 0
    whisper_flag: int = 0
    say_flag: int = 0
    yell_flag: int = 0
    junk_on_cursor: bool = False
    container_looted: bool = False


def _colour_match(actual, expected):
    return all(abs(a - e) <= COLOUR_TOLERANCE for a, e in zip(actual, expected))


def _read_bit(value):
    return 1 if value > 128 else 0


def _find_pixel_bar(img):
    """Find the sync pattern. Returns (bar_x, bar_y, pixel_size, pixel_step) or None."""
    pixels = img.load()
    w, h = img.size

    for y in range(h):
        x = 0
        while x < w - 20:
            r, g, b = pixels[x, y][:3]
            if _colour_match((r, g, b), SYNC1):
                mag_start = x
                while x < w and _colour_match(pixels[x, y][:3], SYNC1):
                    x += 1
                mag_width = x - mag_start

                if mag_width < 3:
                    continue

                gap_start = x
                while x < w and not _colour_match(pixels[x, y][:3], SYNC2):
                    x += 1
                    if x - gap_start > mag_width:
                        break

                if x >= w or not _colour_match(pixels[x, y][:3], SYNC2):
                    continue

                cyan_start = x
                while x < w and _colour_match(pixels[x, y][:3], SYNC2):
                    x += 1
                cyan_width = x - cyan_start

                pixel_size = (mag_width + cyan_width) // 2
                pixel_step = cyan_start - mag_start

                if pixel_size >= 3 and abs(mag_width - cyan_width) <= 3:
                    return (mag_start, y, pixel_size, pixel_step)
            else:
                x += 1

    return None


def _read_pixel(img, bar_x, bar_y, index, pixel_size, pixel_step):
    """Read pixel block at given index, sampling multiple points for accuracy."""
    base_x = bar_x + index * pixel_step
    base_y = bar_y
    samples_r, samples_g, samples_b = [], [], []
    offsets = [pixel_size // 2 - 1, pixel_size // 2, pixel_size // 2 + 1]
    for ox in offsets:
        for oy in offsets:
            x = base_x + ox
            y = base_y + oy
            if 0 <= x < img.width and 0 <= y < img.height:
                r, g, b = img.getpixel((x, y))[:3]
                samples_r.append(r)
                samples_g.append(g)
                samples_b.append(b)
    if not samples_r:
        return (0, 0, 0)
    samples_r.sort()
    samples_g.sort()
    samples_b.sort()
    mid = len(samples_r) // 2
    return (samples_r[mid], samples_g[mid], samples_b[mid])


def _decode_8bit(img, bar_x, bar_y, start_pixel, pixel_size, pixel_step):
    """Decode 8-bit value from 3 consecutive pixels (MSB first, 3 bits per pixel)."""
    bits = []
    for i in range(3):
        r, g, b = _read_pixel(img, bar_x, bar_y, start_pixel + i, pixel_size, pixel_step)
        bits.append(_read_bit(r))
        bits.append(_read_bit(g))
        bits.append(_read_bit(b))
    value = 0
    for i in range(8):
        value = value * 2 + bits[i]
    return value


def _decode_item_id(img, bar_x, bar_y, pixel_size, pixel_step):
    """Decode 18-bit item ID from pixels 8-13."""
    bits = []
    for i in range(ITEM_ID_PIXELS):
        r, g, b = _read_pixel(img, bar_x, bar_y, ITEM_ID_START + i, pixel_size, pixel_step)
        bits.append(_read_bit(r))
        bits.append(_read_bit(g))
        bits.append(_read_bit(b))
    value = 0
    for i in range(18):
        value = value * 2 + bits[i]
    return value


class PixelBridge:
    """Reads Laksefisk addon pixel data from the WoW screen."""

    def __init__(self, scan_region: Optional[dict] = None):
        self._item_lookup: dict = {}
        self._cached_region: Optional[dict] = None
        self._scan_region: Optional[dict] = scan_region
        self._cache_miss: int = 0
        self._screen_w: int = 0
        self._screen_h: int = 0
        self._last_data: Optional[PixelBridgeData] = None
        self._connected: bool = False

        # Load screen dimensions
        with mss.mss() as sct:
            mon = sct.monitors[1]
            self._screen_w = mon["width"]
            self._screen_h = mon["height"]

        # Load item lookup
        lookup_path = os.path.join(os.path.dirname(__file__), "data", "item_lookup.json")
        if os.path.exists(lookup_path):
            try:
                with open(lookup_path, "r", encoding="utf-8") as f:
                    self._item_lookup = json.load(f)
                logger.info(f"Pixel bridge: loaded {len(self._item_lookup)} item lookups")
            except Exception as e:
                logger.warning(f"Pixel bridge: failed to load item lookup: {e}")

    @property
    def connected(self) -> bool:
        """True if the pixel bar was found on the last read."""
        return self._connected

    @property
    def last_data(self) -> Optional[PixelBridgeData]:
        """Last successfully read data."""
        return self._last_data

    def lookup_item(self, item_id: int) -> str:
        """Look up item name from ID."""
        if item_id == 0:
            return ""
        name = self._item_lookup.get(str(item_id))
        if name:
            return name
        return f"Unknown #{item_id}"

    def get_bar_position(self) -> Optional[dict]:
        """Returns the cached bar region, if found."""
        return self._cached_region

    def set_scan_region(self, region: Optional[dict]):
        """Set a custom scan region, or None to revert to bottom-strip auto-detect."""
        self._scan_region = region
        self._cached_region = None
        self._cache_miss = 0

    def reset_cache(self):
        """Force a full rescan on next read."""
        self._cached_region = None
        self._cache_miss = 0

    def read(self) -> Optional[PixelBridgeData]:
        """Read all pixel bridge data from the screen.
        Returns PixelBridgeData on success, None if pixel bar not found.
        """
        img = None
        result = None

        # Fast path: try cached region first
        if self._cached_region:
            img = self._capture_region(self._cached_region)
            result = _find_pixel_bar(img)
            if result:
                self._cache_miss = 0
            else:
                self._cache_miss += 1
                if self._cache_miss >= 3:
                    self._cached_region = None

        # Slow path: scan custom region or bottom strip
        if result is None:
            if self._scan_region:
                strip_region = self._scan_region
                img = self._capture_region(strip_region)
            else:
                img, strip_region = self._capture_bottom_strip()
            result = _find_pixel_bar(img)
            if result:
                bar_x, bar_y, px_size, px_step = result
                bar_w = NUM_PIXELS * px_step + px_size
                pad = 20
                self._cached_region = {
                    "left": max(0, strip_region["left"] + bar_x - pad),
                    "top": max(0, strip_region["top"] + bar_y - pad),
                    "width": bar_w + pad * 2,
                    "height": px_size + pad * 2,
                }
                # Re-capture just the bar region
                img = self._capture_region(self._cached_region)
                result = _find_pixel_bar(img)

        if result is None:
            self._connected = False
            return None

        bar_x, bar_y, px_size, px_step = result
        self._connected = True

        def rp(idx):
            return _read_pixel(img, bar_x, bar_y, idx, px_size, px_step)

        st_r, st_g, st_b = rp(2)
        cnt_r, cnt_g, cnt_b = rp(3)
        chat_r, chat_g, chat_b = rp(4)
        _, _, p7_b = rp(7)

        catch_count = _decode_8bit(img, bar_x, bar_y, 5, px_size, px_step)
        item_id = _decode_item_id(img, bar_x, bar_y, px_size, px_step)
        bait_seconds = _decode_8bit(img, bar_x, bar_y, BAIT_START, px_size, px_step) * 5
        hp_percent = _decode_8bit(img, bar_x, bar_y, HP_START, px_size, px_step)
        p19_r, _, p19_b = rp(19)

        data = PixelBridgeData(
            alive=st_r > 128,
            combat=st_g > 128,
            fishing=st_b > 128,
            loot_parity=_read_bit(cnt_r),
            bags_full=cnt_g > 128,
            cast_parity=_read_bit(cnt_b),
            catch_count=catch_count,
            player_nearby=p7_b > 128,
            item_id=item_id,
            item_name=self.lookup_item(item_id),
            bait_seconds=bait_seconds,
            hp_percent=hp_percent,
            whisper_flag=_read_bit(chat_r),
            say_flag=_read_bit(chat_g),
            yell_flag=_read_bit(chat_b),
            junk_on_cursor=p19_b > 128,
            container_looted=p19_r > 128,
        )

        self._last_data = data
        return data

    def _capture_bottom_strip(self):
        region = {
            "left": 0,
            "top": 0,
            "width": self._screen_w,
            "height": self._screen_h,
        }
        img = self._capture_region(region)
        return img, region

    def _capture_region(self, region):
        with mss.mss() as sct:
            screenshot = sct.grab(region)
            return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
