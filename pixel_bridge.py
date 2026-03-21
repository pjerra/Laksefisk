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
  [20]  Enemy flag — B channel = enemy_nearby
#
# Row 2 (v2 addon only, detected by green version marker below row 1):
#   [21]  Version marker — green (0, 255, 0)
#   [22-33]  Settings (booleans, key indices, slider values)
#   See spec: docs/superpowers/specs/2026-03-22-addon-settings-gui-design.md
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from PIL import Image

from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")

# Must match Laksefisk.lua v8
NUM_PIXELS = 21
ITEM_ID_START = 8
ITEM_ID_PIXELS = 6
BAIT_START = 14
HP_START = 17

# Sync colours
SYNC1 = (255, 0, 255)  # magenta
SYNC2 = (0, 255, 255)  # cyan
VERSION_MARKER_V2 = (0, 255, 0)  # green — pixel 21, identifies v2 addon
COLOUR_TOLERANCE = 20

# How much of the screen bottom to scan (pixels from bottom edge)
SCAN_HEIGHT = 250

# Shared key index → VK code table (must match Laksefisk.lua)
# Index 0 = None/unset
KEY_INDEX_TABLE = [
    None,   # 0: None
    0x31,   # 1: key "1"
    0x32,   # 2: key "2"
    0x33,   # 3: key "3"
    0x34,   # 4: key "4"
    0x35,   # 5: key "5"
    0x36,   # 6: key "6"
    0x37,   # 7: key "7"
    0x38,   # 8: key "8"
    0x39,   # 9: key "9"
    0x30,   # 10: key "0"
    0x70,   # 11: F1
    0x71,   # 12: F2
    0x72,   # 13: F3
    0x73,   # 14: F4
    0x74,   # 15: F5
    0x75,   # 16: F6
    0x76,   # 17: F7
    0x77,   # 18: F8
    0x78,   # 19: F9
    0x79,   # 20: F10
    0x7A,   # 21: F11
    0x7B,   # 22: F12
    0xBD,   # 23: -
    0xBB,   # 24: =
    0x60,   # 25: Num0
    0x61,   # 26: Num1
    0x6B,   # 27: Num+
    0x6D,   # 28: Num-
    0xC0,   # 29: `
    0xDB,   # 30: [
    0xDD,   # 31: ]
]


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
    enemy_nearby: bool = False
    # Addon version: 1 = old (21px), 2 = new (two-row, settings)
    addon_version: int = 1
    # Settings from addon (only populated when addon_version == 2)
    s_stop_friendly: bool = False
    s_stop_enemy: bool = False
    s_stop_bags: bool = False
    s_auto_delete: bool = False
    s_auto_calibrate: bool = False
    s_sound_alerts: bool = False
    s_colour_mode: str = "Red"       # "Red" or "Blue"
    s_skip_party: bool = False
    s_skip_guild: bool = False
    s_skip_friends: bool = False
    s_cast_key: Optional[int] = None       # VK code or None
    s_lure_key: Optional[int] = None       # VK code or None
    s_loot_wait_min: float = 0.6     # seconds
    s_loot_wait_max: float = 2.0     # seconds
    s_colour_multiplier: float = 0.6
    s_colour_closeness_multiplier: float = 2.0


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


def _read_bits_from_channels(img, bar_x, bar_y, pixel_size, pixel_step,
                              start_pixel, start_channel, num_bits, row_y_offset=0):
    """Read num_bits from consecutive RGB channels starting at given pixel/channel.

    Channels are numbered 0=R, 1=G, 2=B within each pixel, continuing across pixels.
    row_y_offset is added to bar_y for reading row 2.
    Returns integer value (MSB first).
    """
    bits = []
    px = start_pixel
    ch = start_channel
    adjusted_y = bar_y + row_y_offset
    for _ in range(num_bits):
        r, g, b = _read_pixel(img, bar_x, adjusted_y, px, pixel_size, pixel_step)
        channels = (r, g, b)
        bits.append(_read_bit(channels[ch]))
        ch += 1
        if ch >= 3:
            ch = 0
            px += 1
    value = 0
    for bit in bits:
        value = value * 2 + bit
    return value


class PixelBridge:
    """Reads Laksefisk addon pixel data from the WoW screen."""

    def __init__(self, wow_screen: 'WowScreen', scan_region: Optional[dict] = None):
        self._wow_screen = wow_screen
        self._item_lookup: dict = {}
        self._cached_region: Optional[dict] = None
        self._scan_region: Optional[dict] = scan_region
        self._cache_miss: int = 0
        self._last_data: Optional[PixelBridgeData] = None
        self._connected: bool = False
        self._consecutive_failures: int = 0

        # Load item lookup
        lookup_path = os.path.join(os.path.dirname(__file__), "item_lookup.json")
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

    @property
    def poll_interval_ms(self) -> int:
        """Recommended poll interval based on consecutive failures (backoff)."""
        if self._consecutive_failures < 5:
            return 2000
        if self._consecutive_failures < 15:
            return 10000
        return 30000

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

    def read(self, allow_slow_scan: bool = True) -> Optional[PixelBridgeData]:
        """Read all pixel bridge data from the screen.
        Returns PixelBridgeData on success, None if pixel bar not found.
        If allow_slow_scan is False, skip the expensive full-screen scan
        when the cached region is lost (used by bot loop to avoid lag).
        """
        img = None
        result = None

        # In backoff and no cache — skip expensive scan unless allowed
        if not allow_slow_scan and not self._cached_region and self._consecutive_failures >= 5:
            return None

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
                    "height": px_size * 2 + pad * 2,
                }
                # Re-capture just the bar region
                img = self._capture_region(self._cached_region)
                result = _find_pixel_bar(img)

        if result is None:
            self._connected = False
            self._consecutive_failures += 1
            return None

        bar_x, bar_y, px_size, px_step = result
        self._connected = True
        self._consecutive_failures = 0

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
        _, _, p20_b = rp(20)

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
            enemy_nearby=p20_b > 128,
        )

        if data.enemy_nearby:
            logger.warning("Enemy player nearby")

        # Check for v2 addon (row 2 settings)
        row2_offset = px_size  # one block height below row 1
        settings = self._read_settings_row(img, bar_x, bar_y, px_size, px_step, row2_offset)
        if settings:
            data.addon_version = 2
            data.s_stop_friendly = settings["stop_friendly"]
            data.s_stop_enemy = settings["stop_enemy"]
            data.s_stop_bags = settings["stop_bags"]
            data.s_auto_delete = settings["auto_delete"]
            data.s_auto_calibrate = settings["auto_calibrate"]
            data.s_sound_alerts = settings["sound_alerts"]
            data.s_colour_mode = settings["colour_mode"]
            data.s_skip_party = settings["skip_party"]
            data.s_skip_guild = settings["skip_guild"]
            data.s_skip_friends = settings["skip_friends"]
            data.s_cast_key = settings["cast_key"]
            data.s_lure_key = settings["lure_key"]
            data.s_loot_wait_min = settings["loot_wait_min"]
            data.s_loot_wait_max = settings["loot_wait_max"]
            data.s_colour_multiplier = settings["colour_multiplier"]
            data.s_colour_closeness_multiplier = settings["colour_closeness_multiplier"]

        self._last_data = data
        return data

    def _read_settings_row(self, img, bar_x, bar_y, px_size, px_step, row_y_offset):
        """Read settings from row 2 pixels. Returns dict of settings or None."""
        # Check version marker at row 2, pixel index 0 (= pixel 21 in spec)
        marker = _read_pixel(img, bar_x, bar_y + row_y_offset, 0, px_size, px_step)
        if not _colour_match(marker, VERSION_MARKER_V2):
            return None

        def rp2(idx):
            return _read_pixel(img, bar_x, bar_y + row_y_offset, idx, px_size, px_step)

        def bits(start_pixel, start_channel, num_bits):
            return _read_bits_from_channels(
                img, bar_x, bar_y, px_size, px_step,
                start_pixel, start_channel, num_bits,
                row_y_offset=row_y_offset
            )

        # Pixel 22 (index 1 in row 2): booleans
        p22_r, p22_g, p22_b = rp2(1)
        # Pixel 23 (index 2): booleans
        p23_r, p23_g, p23_b = rp2(2)
        # Pixel 24 (index 3): colour_mode, skip_party, skip_guild
        p24_r, p24_g, p24_b = rp2(3)
        # Pixel 25 (index 4): skip_friends + cast_key bits 4,3
        p25_r, _, _ = rp2(4)

        # 5-bit cast_key: pixel 25 channels G,B + pixel 26 channels R,G,B
        cast_key_idx = bits(4, 1, 5)  # row2 pixel index 4, channel G

        # 5-bit lure_key: pixel 27 channels R,G,B + pixel 28 R,G
        lure_key_idx = bits(6, 0, 5)  # row2 pixel index 6, channel R

        # 4-bit wait_min: pixel 28 B + pixel 29 R,G,B
        wait_min_raw = bits(7, 2, 4)

        # 4-bit wait_max: pixel 30 R,G,B + pixel 31 R
        wait_max_raw = bits(9, 0, 4)

        # 4-bit colour_mult: pixel 31 G,B + pixel 32 R,G
        col_mult_raw = bits(10, 1, 4)

        # 4-bit colour_close: pixel 32 B + pixel 33 R,G,B
        col_close_raw = bits(11, 2, 4)

        # Decode key indices to VK codes
        cast_vk = KEY_INDEX_TABLE[cast_key_idx] if cast_key_idx < len(KEY_INDEX_TABLE) else None
        lure_vk = KEY_INDEX_TABLE[lure_key_idx] if lure_key_idx < len(KEY_INDEX_TABLE) else None

        return {
            "stop_friendly": p22_r > 128,
            "stop_enemy": p22_g > 128,
            "stop_bags": p22_b > 128,
            "auto_delete": p23_r > 128,
            "auto_calibrate": p23_g > 128,
            "sound_alerts": p23_b > 128,
            "colour_mode": "Blue" if p24_r > 128 else "Red",
            "skip_party": p24_g > 128,
            "skip_guild": p24_b > 128,
            "skip_friends": p25_r > 128,
            "cast_key": cast_vk,
            "lure_key": lure_vk,
            "loot_wait_min": round(wait_min_raw * 0.2, 1),
            "loot_wait_max": round(wait_max_raw * 0.2, 1),
            "colour_multiplier": round(col_mult_raw * 0.2, 1),
            "colour_closeness_multiplier": round(col_close_raw * (5.0 / 15), 2),
        }

    def _capture_bottom_strip(self):
        """Capture the bottom 250px of the WoW client area."""
        cw, ch = self._wow_screen.client_size
        y_start = max(0, ch - SCAN_HEIGHT)
        h = ch - y_start
        img = self._wow_screen.get_region(0, y_start, cw, h)
        region = {"left": 0, "top": y_start, "width": cw, "height": h}
        return img, region

    def _capture_region(self, region):
        """Capture a region relative to the WoW client area."""
        return self._wow_screen.get_region(
            region["left"], region["top"],
            region["width"], region["height"],
        )
