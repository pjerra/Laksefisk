"""
Test: Read Laksefisk addon pixels from the WoW screen (v8 — binary encoding).

Auto-scans the bottom of the screen for the magenta→cyan sync pattern.
No manual region needed — just run it with WoW open.

Pixel layout:
  [0]  Sync 1 — magenta    [1]  Sync 2 — cyan
  [2]  Status: alive/combat/fishing
  [3]  Counters: loot_parity / bags_full / cast_parity
  [4]  Chat: whisper/say/yell parity
  [5-7]  Catch count (8-bit binary, MSB first) — pixel 7 B = player nearby
  [8-13]  Item ID (18-bit binary, MSB first)
  [14-16] Bait time remaining (seconds/5, 8-bit binary, 0=no bait)
  [17-19] Player HP percent (8-bit binary, 0-100)

Press 'r' to read, 'l' for live, 'q' to quit.
"""

import sys
import os
import json
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import mss
from PIL import Image, ImageDraw, ImageTk

# Must match Laksefisk.lua v8
NUM_PIXELS = 20
ITEM_ID_START = 8      # pixels 8-13 encode item ID (18-bit binary)
ITEM_ID_PIXELS = 6
BAIT_START = 14        # pixels 14-16 encode bait remaining
HP_START = 17          # pixels 17-19 encode player HP percent

# Sync colours
SYNC1 = (255, 0, 255)  # magenta
SYNC2 = (0, 255, 255)  # cyan
COLOUR_TOLERANCE = 20

# How much of the screen bottom to scan (pixels from bottom edge)
SCAN_HEIGHT = 250

# Item lookup table
ITEM_LOOKUP = {}
_lookup_path = os.path.join(os.path.dirname(__file__), "..", "data", "item_lookup.json")
if os.path.exists(_lookup_path):
    with open(_lookup_path, "r", encoding="utf-8") as f:
        ITEM_LOOKUP = json.load(f)


def colour_match(actual, expected):
    return all(abs(a - e) <= COLOUR_TOLERANCE for a, e in zip(actual, expected))


def find_pixel_bar(img):
    """Find the sync pattern and auto-detect pixel size/step.
    Returns (bar_x, bar_y, pixel_size, pixel_step) or None.
    """
    pixels = img.load()
    w, h = img.size

    for y in range(h):
        x = 0
        while x < w - 20:
            r, g, b = pixels[x, y][:3]
            if colour_match((r, g, b), SYNC1):
                mag_start = x
                while x < w and colour_match(pixels[x, y][:3], SYNC1):
                    x += 1
                mag_end = x
                mag_width = mag_end - mag_start

                if mag_width < 3:
                    continue

                gap_start = x
                while x < w and not colour_match(pixels[x, y][:3], SYNC2):
                    x += 1
                    if x - gap_start > mag_width:
                        break

                if x >= w or not colour_match(pixels[x, y][:3], SYNC2):
                    continue

                cyan_start = x
                while x < w and colour_match(pixels[x, y][:3], SYNC2):
                    x += 1
                cyan_width = x - cyan_start

                pixel_size = (mag_width + cyan_width) // 2
                pixel_step = cyan_start - mag_start

                if pixel_size >= 3 and abs(mag_width - cyan_width) <= 3:
                    return (mag_start, y, pixel_size, pixel_step)
            else:
                x += 1

    return None


def read_pixel(img, bar_x, bar_y, index, pixel_size, pixel_step):
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


def read_bit(value):
    """Binary decode: >128 = 1, <=128 = 0"""
    return 1 if value > 128 else 0


def decode_8bit(img, bar_x, bar_y, start_pixel, pixel_size, pixel_step):
    """Decode 8-bit value from 3 consecutive pixels (MSB first, 3 bits per pixel)."""
    bits = []
    for i in range(3):
        r, g, b = read_pixel(img, bar_x, bar_y, start_pixel + i, pixel_size, pixel_step)
        bits.append(read_bit(r))
        bits.append(read_bit(g))
        bits.append(read_bit(b))
    value = 0
    for i in range(8):
        value = value * 2 + bits[i]
    return value


def decode_item_id(img, bar_x, bar_y, pixel_size, pixel_step):
    """Decode 18-bit item ID from pixels 8-13 (MSB first, 3 bits per pixel)."""
    bits = []
    for i in range(ITEM_ID_PIXELS):
        r, g, b = read_pixel(img, bar_x, bar_y, ITEM_ID_START + i, pixel_size, pixel_step)
        bits.append(read_bit(r))
        bits.append(read_bit(g))
        bits.append(read_bit(b))
    value = 0
    for i in range(18):
        value = value * 2 + bits[i]
    return value


def lookup_item_name(item_id):
    """Look up item name from ID. Returns name or 'Unknown #ID'."""
    if item_id == 0:
        return "(none)"
    name = ITEM_LOOKUP.get(str(item_id))
    if name:
        return name
    return f"Unknown #{item_id}"


def read_all(img, bar_x, bar_y, pixel_size, pixel_step):
    def rp(idx):
        return read_pixel(img, bar_x, bar_y, idx, pixel_size, pixel_step)

    st_r, st_g, st_b = rp(2)
    cnt_r, cnt_g, cnt_b = rp(3)
    chat_r, chat_g, chat_b = rp(4)
    catch_count = decode_8bit(img, bar_x, bar_y, 5, pixel_size, pixel_step)
    item_id = decode_item_id(img, bar_x, bar_y, pixel_size, pixel_step)
    bait_seconds = decode_8bit(img, bar_x, bar_y, BAIT_START, pixel_size, pixel_step) * 5
    hp_percent = decode_8bit(img, bar_x, bar_y, HP_START, pixel_size, pixel_step)

    # Pixel 7 blue channel = player nearby flag
    _, _, p7_b = rp(7)

    return {
        "alive": st_r > 128,
        "combat": st_g > 128,
        "fishing": st_b > 128,
        "loot_parity": read_bit(cnt_r),
        "bags_full": cnt_g > 128,
        "cast_parity": read_bit(cnt_b),
        "catch_count": catch_count,
        "player_nearby": p7_b > 128,
        "item_id": item_id,
        "item_name": lookup_item_name(item_id),
        "bait_seconds": bait_seconds,
        "hp_percent": hp_percent,
        "whisper_flag": read_bit(chat_r),
        "say_flag": read_bit(chat_g),
        "yell_flag": read_bit(chat_b),
    }


class PixelReaderTest:
    def __init__(self):
        with mss.mss() as sct:
            mon = sct.monitors[1]
            self._screen_w = mon["width"]
            self._screen_h = mon["height"]

        self.root = tk.Tk()
        self.root.title("Pixel Reader v8 — auto-detect")
        self.root.configure(bg="#111")
        self.root.geometry("620x540+50+50")
        self.root.attributes("-topmost", True)

        self._photo = None
        self._live = False
        self._live_id = None

        # Cached bar position on screen (absolute coords) for fast re-reads
        self._cached_region = None  # {left, top, width, height}
        self._cache_miss = 0

        self._preview_label = tk.Label(self.root, bg="#222")
        self._preview_label.pack(padx=10, pady=10)

        self._text = tk.Text(self.root, bg="#111", fg="#4FC3F7",
                             font=("Consolas", 11), height=18, state="disabled",
                             relief="flat", highlightthickness=0)
        self._text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        btn_frame = tk.Frame(self.root, bg="#111")
        btn_frame.pack(pady=(0, 10))

        tk.Button(btn_frame, text="Read (R)", command=self._read,
                  bg="#1a2233", fg="#4FC3F7", font=("Segoe UI", 10),
                  relief="flat", padx=12).pack(side="left", padx=4)
        self._live_btn = tk.Button(btn_frame, text="Live (L)", command=self._toggle_live,
                                   bg="#1a2233", fg="#4FC3F7", font=("Segoe UI", 10),
                                   relief="flat", padx=12)
        self._live_btn.pack(side="left", padx=4)
        tk.Button(btn_frame, text="Rescan (S)", command=self._rescan,
                  bg="#1a4a1a", fg="#4FC3F7", font=("Segoe UI", 10),
                  relief="flat", padx=12).pack(side="left", padx=4)
        tk.Button(btn_frame, text="Quit (Q)", command=self.root.destroy,
                  bg="#1a2233", fg="#999", font=("Segoe UI", 10),
                  relief="flat", padx=12).pack(side="left", padx=4)

        self.root.bind("<r>", lambda e: self._read())
        self.root.bind("<l>", lambda e: self._toggle_live())
        self.root.bind("<s>", lambda e: self._rescan())
        self.root.bind("<q>", lambda e: self.root.destroy())

        self._show_msg("Press R to scan for pixel bar, or L for live mode.\n"
                       "The addon's magenta+cyan sync pixels will be found automatically.\n\n"
                       f"Item lookup: {len(ITEM_LOOKUP)} items loaded")

    # ── Screen capture ──

    def _capture_bottom_strip(self):
        """Capture the bottom strip of the primary monitor."""
        region = {
            "left": 0,
            "top": self._screen_h - SCAN_HEIGHT,
            "width": self._screen_w,
            "height": SCAN_HEIGHT,
        }
        with mss.mss() as sct:
            screenshot = sct.grab(region)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img, region

    def _capture_cached_region(self):
        """Capture just the cached bar region (fast path for live mode)."""
        with mss.mss() as sct:
            screenshot = sct.grab(self._cached_region)
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        return img

    def _rescan(self):
        """Force a full-screen scan, clearing the cache."""
        self._cached_region = None
        self._cache_miss = 0
        self._read()

    # ── Read ──

    def _read(self):
        img = None
        bar_x = bar_y = px_size = px_step = 0
        result = None
        screen_x = screen_y = 0  # absolute screen position of image origin

        # Fast path: try cached region first
        if self._cached_region:
            img = self._capture_cached_region()
            result = find_pixel_bar(img)
            if result:
                bar_x, bar_y, px_size, px_step = result
                screen_x = self._cached_region["left"]
                screen_y = self._cached_region["top"]
                self._cache_miss = 0
            else:
                self._cache_miss += 1
                if self._cache_miss >= 3:
                    self._cached_region = None

        # Slow path: scan bottom strip
        if result is None:
            img, strip_region = self._capture_bottom_strip()
            result = find_pixel_bar(img)
            if result:
                bar_x, bar_y, px_size, px_step = result
                screen_x = strip_region["left"]
                screen_y = strip_region["top"]

                # Cache the found position with padding
                bar_w = NUM_PIXELS * px_step + px_size
                pad = 20
                self._cached_region = {
                    "left": max(0, screen_x + bar_x - pad),
                    "top": max(0, screen_y + bar_y - pad),
                    "width": bar_w + pad * 2,
                    "height": px_size + pad * 2,
                }
                # Re-capture just the bar region so coordinates are clean
                img = self._capture_cached_region()
                result = find_pixel_bar(img)
                if result:
                    bar_x, bar_y, px_size, px_step = result
                    screen_x = self._cached_region["left"]
                    screen_y = self._cached_region["top"]

        # Preview
        if img is not None:
            scale = max(2, min(580 // max(img.width, 1), 40))
            preview = img.resize((img.width * scale, img.height * scale), Image.NEAREST)
            if result is not None:
                draw = ImageDraw.Draw(preview)
                for i in range(NUM_PIXELS):
                    cx = (bar_x + i * px_step + px_size // 2) * scale
                    cy = (bar_y + px_size // 2) * scale
                    sz = max(2, scale)
                    draw.line([(cx - sz, cy), (cx + sz, cy)], fill=(255, 0, 0), width=1)
                    draw.line([(cx, cy - sz), (cx, cy + sz)], fill=(255, 0, 0), width=1)
                    lx = (bar_x + i * px_step) * scale
                    rx = lx + px_size * scale
                    ty = bar_y * scale
                    by = ty + px_size * scale
                    draw.rectangle([(lx, ty), (rx, by)], outline=(255, 255, 0), width=1)
            self._photo = ImageTk.PhotoImage(preview)
            self._preview_label.config(image=self._photo)

        self._text.config(state="normal")
        self._text.delete("1.0", "end")

        if result is None:
            self._text.insert("end", "Pixel bar NOT FOUND\n\n")
            self._text.insert("end", f"Scanned bottom {SCAN_HEIGHT}px of screen ({self._screen_w}x{self._screen_h})\n")
            self._text.insert("end", "\nMake sure WoW is running and the Laksefisk addon is loaded.\n")
            self._text.insert("end", "The pixel bar should be visible near the bottom of the screen.\n")
            self._text.insert("end", "Press S to force a rescan.\n")
        else:
            data = read_all(img, bar_x, bar_y, px_size, px_step)

            s1 = read_pixel(img, bar_x, bar_y, 0, px_size, px_step)
            s2 = read_pixel(img, bar_x, bar_y, 1, px_size, px_step)

            abs_x = screen_x + bar_x
            abs_y = screen_y + bar_y
            self._text.insert("end", f"Found at screen ({abs_x},{abs_y})  "
                              f"pixel={px_size}px  step={px_step}px\n")
            self._text.insert("end", f"{'─' * 44}\n")
            self._text.insert("end", f"  Sync 1:       {s1} {'OK' if colour_match(s1, SYNC1) else 'BAD'}\n")
            self._text.insert("end", f"  Sync 2:       {s2} {'OK' if colour_match(s2, SYNC2) else 'BAD'}\n")
            self._text.insert("end", f"{'─' * 44}\n")
            self._text.insert("end", f"  Alive:        {'YES' if data['alive'] else 'DEAD'}\n")
            self._text.insert("end", f"  In combat:    {'YES' if data['combat'] else 'no'}\n")
            self._text.insert("end", f"  Fishing:      {'YES' if data['fishing'] else 'no'}\n")
            self._text.insert("end", f"{'─' * 44}\n")
            self._text.insert("end", f"  Catch count:  {data['catch_count']}\n")
            bait = data['bait_seconds']
            if bait > 0:
                mins = bait // 60
                secs = bait % 60
                self._text.insert("end", f"  Bait:         {mins}m {secs}s remaining\n")
            else:
                self._text.insert("end", f"  Bait:         NONE\n")
            self._text.insert("end", f"  HP:           {data['hp_percent']}%\n")
            self._text.insert("end", f"  Loot parity:  {data['loot_parity']}\n")
            self._text.insert("end", f"  Cast parity:  {data['cast_parity']}\n")
            self._text.insert("end", f"  Bags full:    {'YES' if data['bags_full'] else 'no'}\n")
            self._text.insert("end", f"  Player nearby:{'YES' if data['player_nearby'] else 'no'}\n")
            self._text.insert("end", f"  Item ID:      {data['item_id']}\n")
            self._text.insert("end", f"  Item name:    {data['item_name']}\n")
            self._text.insert("end", f"{'─' * 44}\n")
            self._text.insert("end", f"  Whisper flag: {data['whisper_flag']}\n")
            self._text.insert("end", f"  Say flag:     {data['say_flag']}\n")
            self._text.insert("end", f"  Yell flag:    {data['yell_flag']}\n")

            # Raw pixel values
            self._text.insert("end", f"\n{'─' * 44}\n")
            self._text.insert("end", "  Raw pixel values:\n")
            for i in range(NUM_PIXELS):
                rgb = read_pixel(img, bar_x, bar_y, i, px_size, px_step)
                bits = f"[{read_bit(rgb[0])}{read_bit(rgb[1])}{read_bit(rgb[2])}]"
                self._text.insert("end", f"    [{i:2d}] {rgb}  {bits}\n")

        self._text.config(state="disabled")

    def _show_msg(self, msg):
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.insert("end", msg)
        self._text.config(state="disabled")

    def _toggle_live(self):
        self._live = not self._live
        if self._live:
            self._live_btn.config(text="Stop", bg="#663333")
            self._live_update()
        else:
            self._live_btn.config(text="Live (L)", bg="#1a2233")
            if self._live_id:
                self.root.after_cancel(self._live_id)
                self._live_id = None

    def _live_update(self):
        if not self._live:
            return
        self._read()
        self._live_id = self.root.after(250, self._live_update)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    PixelReaderTest().run()
