"""
Laksefisk GUI — Python/tkinter port of the WPF Material Design UI.

Window sits in the TOP strip of the screen (above WoW's capture zone).
WowScreen captures the centre half, so the top quarter is safe.
Always-on-top so it stays visible over WoW.

Lure macro — presses lure key every 10 min 10 sec, waits 5 sec.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import random
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageTk

import wow_process
from bite_watcher import PositionBiteWatcher
from bobber_finder import SearchBobberFinder
from fish_tracker import FishTracker, find_wow_log_path
from fishing_bot import LaksefiskBot
from models import BobberBitmapEvent, FishingAction, FishingEvent
from pixel_classifier import ClassifierMode, PixelClassifier
from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_SCRIPT_DIR, "config.json")
STRIKE_VALUE = 7

DEFAULT_CONFIG = {
    "cast_key": 0x34,
    "lure_key": None,
    "loot_wait_min": 0.5,
    "loot_wait_max": 2.0,
    "colour_mode": "Red",
    "colour_multiplier": 0.5,
    "colour_closeness_multiplier": 2.0,
    "wow_log_path": None,
}


def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            return {**DEFAULT_CONFIG, **cfg}
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def _save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# Colours matching the original WPF Material Design theme
BG_WHITE = "#FFFFFF"
LIGHT_BLUE = "#ADD8E6"
CARD_BG = "#FAFAFA"
TEXT_DARK = "#212121"
TEXT_GREY = "#757575"
CHART_RED = "#F34336"
CHART_BLUE_FILL = "#ADD8E6"
CHART_GRID = "#DADADA"


# ---------------------------------------------------------------------------
# Reticle drawer
# ---------------------------------------------------------------------------

def draw_reticle(img: Image.Image, point: Tuple[int, int]) -> Image.Image:
    img = img.copy()
    draw = ImageDraw.Draw(img)
    x, y = point
    if x <= 0 and y <= 0:
        return img
    cs, rs = 15, 40
    c = "white"
    w = 2

    def corner(cx, cy, dx, dy):
        draw.line([(cx + dx, cy), (cx, cy), (cx, cy + dy)], fill=c, width=w)

    corner(x - rs, y - rs,  cs,  cs)
    corner(x - rs, y + rs,  cs, -cs)
    corner(x + rs, y - rs, -cs,  cs)
    corner(x + rs, y + rs, -cs, -cs)
    draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=c)
    return img


# ---------------------------------------------------------------------------
# Custom canvas-based live chart
# ---------------------------------------------------------------------------

class BobberChart(tk.Canvas):
    def __init__(self, parent, strike_value: int = 7, **kw):
        kw.setdefault("bg", BG_WHITE)
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self.strike = strike_value
        self._data: deque = deque(maxlen=120)
        self.bind("<Configure>", lambda e: self._draw())

    def add(self, value: int):
        self._data.append((time.time(), value))
        self._draw()

    def clear_chart(self):
        self._data.clear()
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10 or h < 10:
            return

        ml, mr, mt, mb = 4, 4, 4, 4
        cw = w - ml - mr
        ch = h - mt - mb
        y_min_val, y_max_val = -15, 10

        def y_to_px(v):
            return mt + ch - ((v - y_min_val) / (y_max_val - y_min_val)) * ch

        for v in range(-15, 11, 5):
            py = y_to_px(v)
            self.create_line(ml, py, w - mr, py, fill=CHART_GRID, width=1)

        zero_y = y_to_px(0)
        bottom_y = y_to_px(y_min_val)
        self.create_rectangle(ml, zero_y, w - mr, bottom_y, fill="#E3F2FD", outline="")

        strike_y = y_to_px(-self.strike)
        self.create_line(ml, strike_y, w - mr, strike_y, fill="black", width=1, dash=(4, 4))

        if len(self._data) < 2:
            return

        now = time.time()
        window = 25

        points = []
        for t, v in self._data:
            elapsed = t - (now - window)
            if elapsed < 0:
                continue
            px = ml + (elapsed / window) * cw
            py = y_to_px(v)
            points.append((px, py))

        if len(points) < 2:
            return

        fill_coords = []
        for px, py in points:
            fill_coords.extend([px, py])
        fill_coords.extend([points[-1][0], zero_y, points[0][0], zero_y])
        self.create_polygon(*fill_coords, fill=CHART_BLUE_FILL, outline="")

        flat = []
        for px, py in points:
            flat.extend([px, py])
        self.create_line(*flat, fill=CHART_RED, width=3, smooth=False)

        for px, py in points:
            r = 3
            self.create_oval(px - r, py - r, px + r, py + r, fill="#9E9E9E", outline="#757575")


# ---------------------------------------------------------------------------
# Flying fish overlay
# ---------------------------------------------------------------------------

class FlyingFishOverlay:
    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        self._fish: List[dict] = []
        self._running = False
        self._rng = random.Random()
        self._after_id: Optional[str] = None

    def start(self):
        self._stop()
        w = self.canvas.winfo_width() or 500
        h = self.canvas.winfo_height() or 200
        self.canvas.delete("fish")
        self._fish.clear()
        for i in range(12):
            x = self._rng.randint(0, w)
            y = self._rng.randint(0, h)
            fid = self.canvas.create_text(x, y, text="\U0001F41F", font=("Arial", 16), tags="fish")
            self._fish.append({
                "id": fid, "x": x, "y": y,
                "sx": self._rng.randint(-3, 3),
                "sy": self._rng.randint(1, 4),
            })
        self._running = True
        self._tick()

    def stop(self):
        self._stop()
        self.canvas.delete("fish")
        self._fish.clear()

    def _stop(self):
        self._running = False
        if self._after_id:
            try:
                self.canvas.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self):
        if not self._running:
            return
        w = self.canvas.winfo_width() or 500
        h = self.canvas.winfo_height() or 200
        for f in self._fish:
            f["x"] = (f["x"] + f["sx"]) % w
            f["y"] = (f["y"] + f["sy"]) % h
            self.canvas.coords(f["id"], f["x"], f["y"])
        self._after_id = self.canvas.after(33, self._tick)


# ---------------------------------------------------------------------------
# Colour Configuration Window
# ---------------------------------------------------------------------------

class ColourConfigWindow(tk.Toplevel):
    def __init__(self, parent, pixel_classifier: PixelClassifier, on_change=None):
        super().__init__(parent)
        self.title("Colour Explorer")
        self.configure(bg=BG_WHITE)
        self.pc = pixel_classifier
        self._on_change = on_change
        self._screen_capture: Optional[Image.Image] = None
        self._colour_photo: Optional[ImageTk.PhotoImage] = None
        self._screen_photo: Optional[ImageTk.PhotoImage] = None

        self.attributes("-topmost", True)
        self._build()
        self._update_labels()
        self._render(True)

        # Set geometry AFTER content is built so it sticks
        self.update_idletasks()
        win_w, win_h = 620, 420
        sx = (self.winfo_screenwidth() - win_w) // 2
        sy = (self.winfo_screenheight() - win_h) // 2
        self.geometry(f"{win_w}x{win_h}+{sx}+{sy}")
        self.resizable(False, False)

    def _build(self):
        top = tk.Frame(self, bg=BG_WHITE)
        top.pack(fill="both", expand=True, padx=8, pady=4)
        top.columnconfigure(0, weight=0)
        top.columnconfigure(1, weight=1)
        top.columnconfigure(2, weight=1)
        top.rowconfigure(2, weight=1)

        self._lbl_colour = tk.Label(top, text="Red:", bg=BG_WHITE, fg=TEXT_DARK, font=("Segoe UI", 9))
        self._lbl_colour.grid(row=0, column=0, sticky="w", padx=4)

        self._find_var = tk.IntVar(value=100)
        self._lbl_val = tk.Label(top, textvariable=self._find_var, bg=BG_WHITE, fg=TEXT_DARK, font=("Segoe UI", 9))
        self._lbl_val.grid(row=1, column=0, padx=4)

        self._slider_find = tk.Scale(top, from_=255, to=0, orient="vertical", variable=self._find_var,
                                     bg=BG_WHITE, fg=TEXT_DARK, troughcolor=LIGHT_BLUE, highlightthickness=0,
                                     command=lambda _: self._render(False), length=200)
        self._slider_find.grid(row=2, column=0, sticky="ns", padx=4)

        self._colour_label = tk.Label(top, bg="black")
        self._colour_label.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=4, pady=4)

        self._screen_label = tk.Label(top, bg="black")
        self._screen_label.grid(row=0, column=2, rowspan=3, sticky="nsew", padx=4, pady=4)

        bot = tk.Frame(self, bg=BG_WHITE)
        bot.pack(fill="x", padx=8, pady=4)

        left_sliders = tk.Frame(bot, bg=BG_WHITE)
        left_sliders.pack(side="left", fill="x", expand=True)

        self._lbl_mult = tk.Label(left_sliders, text="", bg=BG_WHITE, fg=TEXT_DARK, font=("Segoe UI", 8),
                                  wraplength=320, anchor="w", justify="left")
        self._lbl_mult.pack(anchor="w")
        self._mult_var = tk.IntVar(value=int(self.pc.colour_multiplier * 100))
        tk.Scale(left_sliders, from_=0, to=300, orient="horizontal", variable=self._mult_var,
                 bg=BG_WHITE, troughcolor=LIGHT_BLUE, highlightthickness=0, length=280,
                 command=lambda _: self._on_mult()).pack(anchor="w", padx=16)

        self._lbl_close = tk.Label(left_sliders, text="", bg=BG_WHITE, fg=TEXT_DARK, font=("Segoe UI", 8),
                                   wraplength=320, anchor="w", justify="left")
        self._lbl_close.pack(anchor="w")
        self._close_var = tk.IntVar(value=int(self.pc.colour_closeness_multiplier * 100))
        tk.Scale(left_sliders, from_=0, to=500, orient="horizontal", variable=self._close_var,
                 bg=BG_WHITE, troughcolor=LIGHT_BLUE, highlightthickness=0, length=280,
                 command=lambda _: self._on_close()).pack(anchor="w", padx=16)

        right_ctrl = tk.Frame(bot, bg=BG_WHITE)
        right_ctrl.pack(side="right", padx=8)

        tk.Button(right_ctrl, text="Capture Screen", bg=LIGHT_BLUE, fg=TEXT_DARK,
                  relief="flat", padx=12, pady=4, command=self._on_capture).pack(pady=4)

        mode_row = tk.Frame(right_ctrl, bg=BG_WHITE)
        mode_row.pack(pady=2)
        tk.Label(mode_row, text="Watch Feather:", bg=BG_WHITE, fg=TEXT_DARK, font=("Segoe UI", 8)).pack(side="left")
        self._mode_var = tk.StringVar(value="Red" if self.pc.mode == ClassifierMode.Red else "Blue")
        om = ttk.Combobox(mode_row, textvariable=self._mode_var, values=["Red", "Blue"],
                          width=6, state="readonly")
        om.pack(side="left", padx=4)
        om.bind("<<ComboboxSelected>>", lambda _: self._on_mode_change())

    def _on_mode_change(self):
        self.pc.mode = ClassifierMode.Red if self._mode_var.get() == "Red" else ClassifierMode.Blue
        self._update_labels()
        self._render(True)
        if self._on_change:
            self._on_change()

    def _on_mult(self):
        self.pc.colour_multiplier = self._mult_var.get() / 100
        self._update_labels()
        self._render(True)
        if self._on_change:
            self._on_change()

    def _on_close(self):
        self.pc.colour_closeness_multiplier = self._close_var.get() / 100
        self._update_labels()
        self._render(True)
        if self._on_change:
            self._on_change()

    def _on_capture(self):
        self._screen_capture = WowScreen.get_bitmap()
        self._render(True)

    def _update_labels(self):
        primary = self._mode_var.get()
        secondary = "blue" if primary == "Red" else "red"
        self._lbl_colour.config(text=f"{primary}:")
        self._lbl_mult.config(text=(
            f"{primary} multiplied by {self.pc.colour_multiplier:.2f} "
            f"must be greater than green and {secondary}."
        ))
        self._lbl_close.config(text=(
            f"How close green and {secondary} need to be: "
            f"{self.pc.colour_closeness_multiplier:.2f}"
        ))

    def _render(self, render_matched: bool):
        find_val = self._find_var.get()
        bitmap = Image.new("RGB", (256, 256))
        pixels = bitmap.load()
        matched: List[Tuple[int, int]] = []

        for i in range(256):
            for g in range(256):
                r, b = find_val, i
                if self.pc.mode == ClassifierMode.Blue:
                    r, b = i, find_val
                pixels[i, g] = (r, g, b)
                if self.pc.is_match(r, g, b):
                    matched.append((i, g))

        if render_matched and matched:
            matched_set = set(matched)
            for px, py in matched:
                neighbors = [(px, py - 1), (px, py + 1), (px - 1, py), (px + 1, py)]
                if sum(1 for n in neighbors if n in matched_set) < 4:
                    pixels[px, py] = (255, 255, 255)

        self._colour_photo = ImageTk.PhotoImage(bitmap)
        self._colour_label.config(image=self._colour_photo)

        if render_matched and self._screen_capture:
            bmp = self._screen_capture.copy()
            spix = bmp.load()
            for x in range(bmp.width):
                for y in range(bmp.height):
                    sr, sg, sb = spix[x, y][:3]
                    if self.pc.is_match(sr, sg, sb):
                        spix[x, y] = (0, 0, 255) if self.pc.mode == ClassifierMode.Blue else (255, 0, 0)
            # Resize to exactly 256x256 so the window layout doesn't shift
            bmp = bmp.resize((256, 256), Image.LANCZOS)
            self._screen_photo = ImageTk.PhotoImage(bmp)
            self._screen_label.config(image=self._screen_photo)


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Laksefisk")
        self.configure(bg=BG_WHITE)

        # Position in top strip of screen — this area is NOT captured by
        # WowScreen (which grabs the centre half starting at height/4).
        # Full screen width, height = screen_height/4.
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        win_h = screen_h // 4
        self.geometry(f"{screen_w}x{win_h}+0+0")
        self.minsize(800, 200)

        # Always on top so WoW doesn't cover it
        self.attributes("-topmost", True)

        self._cfg = _load_config()

        self._pc = PixelClassifier()
        self._pc.colour_multiplier = self._cfg["colour_multiplier"]
        self._pc.colour_closeness_multiplier = self._cfg["colour_closeness_multiplier"]
        self._pc.mode = ClassifierMode.Red if self._cfg["colour_mode"] == "Red" else ClassifierMode.Blue
        self._pc.set_configuration(wow_process.is_wow_classic())
        self._bobber_finder = SearchBobberFinder(self._pc)
        self._bite_watcher = PositionBiteWatcher(STRIKE_VALUE)
        self._bot: Optional[LaksefiskBot] = None
        self._bot_thread: Optional[threading.Thread] = None
        self._cast_key = self._cfg["cast_key"]
        self._lure_key: Optional[int] = self._cfg["lure_key"]
        self._loot_min = self._cfg["loot_wait_min"]
        self._loot_max = self._cfg["loot_wait_max"]

        self._log_queue: queue.Queue = queue.Queue()
        self._screenshot_photo: Optional[ImageTk.PhotoImage] = None

        # Fish tracker
        log_path = self._cfg.get("wow_log_path") or find_wow_log_path()
        self._fish_tracker = FishTracker(log_path)
        self._fish_tracker.set_on_update(lambda: self.after(0, self._update_fish_display))

        self._bobber_finder.bitmap_callbacks.append(self._on_bitmap_event)

        self._build_ui()
        self._setup_logging()
        self._fish_tracker.start()
        self._poll()

    # ------------------------------------------------------------------
    # UI — horizontal layout to fill the wide top strip
    # ------------------------------------------------------------------
    #
    #  ┌──────────────────────────────────────────────────────────────┐
    #  │ [▶][■][⚙] Cast:[4] Lure:[5]  Status │  Screenshot  │ Chart │
    #  │                                      │  (with       │       │
    #  │              Log                     │  reticle)    │       │
    #  └──────────────────────────────────────────────────────────────┘

    def _build_ui(self):
        main = tk.Frame(self, bg=BG_WHITE)
        main.pack(fill="both", expand=True)
        # 3 columns: controls+log (30%) | screenshot (45%) | chart (25%)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=5)
        main.columnconfigure(2, weight=2, minsize=200)
        main.rowconfigure(0, weight=1)

        # ── LEFT: toolbar + log ──────────────────────────────────────
        left = tk.Frame(main, bg=BG_WHITE)
        left.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        # Toolbar
        toolbar = tk.Frame(left, bg=CARD_BG, relief="solid", bd=1)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        btn_kw = dict(bg=BG_WHITE, fg=TEXT_DARK, relief="flat", bd=0, padx=6, pady=4,
                      font=("Segoe UI", 12), cursor="hand2", activebackground=LIGHT_BLUE)

        self._btn_play = tk.Button(toolbar, text="\u25B6", command=self._on_play, **btn_kw)
        self._btn_play.pack(side="left", padx=2, pady=2)

        self._btn_stop = tk.Button(toolbar, text="\u25A0", command=self._on_stop,
                                   state="disabled", **btn_kw)
        self._btn_stop.pack(side="left", padx=2, pady=2)

        tk.Button(toolbar, text="\u2699", command=self._on_settings, **btn_kw).pack(side="left", padx=2, pady=2)

        # Separator
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=4, pady=4)

        # Cast key
        tk.Label(toolbar, text="Cast:", bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 9)).pack(side="left", padx=(4, 2))
        self._cast_key_var = tk.StringVar(value=self._vk_to_label(self._cast_key))
        cast_entry = tk.Entry(toolbar, textvariable=self._cast_key_var, width=3,
                              font=("Segoe UI", 11, "bold"), justify="center",
                              bg=LIGHT_BLUE, fg=TEXT_DARK, relief="flat", bd=2)
        cast_entry.pack(side="left", padx=2)
        cast_entry.bind("<FocusIn>", lambda e: self._cast_key_var.set(""))
        cast_entry.bind("<FocusOut>", lambda e: self._cast_key_var.set(self._vk_to_label(self._cast_key)))
        cast_entry.bind("<KeyRelease>", self._on_cast_key_entry)

        # Loot delay (min–max seconds)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=4, pady=4)
        tk.Label(toolbar, text="Loot wait:", bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 9)).pack(side="left", padx=(4, 2))

        self._loot_min_var = tk.DoubleVar(value=self._loot_min)
        loot_min_spin = tk.Spinbox(toolbar, from_=0.0, to=10.0, increment=0.1,
                                   textvariable=self._loot_min_var, width=4,
                                   font=("Segoe UI", 9), bg=LIGHT_BLUE, relief="flat",
                                   command=self._on_loot_delay_change)
        loot_min_spin.pack(side="left", padx=1)
        loot_min_spin.bind("<FocusOut>", lambda e: self._on_loot_delay_change())
        loot_min_spin.bind("<Return>", lambda e: self._on_loot_delay_change())

        tk.Label(toolbar, text="-", bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 9)).pack(side="left")

        self._loot_max_var = tk.DoubleVar(value=self._loot_max)
        loot_max_spin = tk.Spinbox(toolbar, from_=0.0, to=10.0, increment=0.1,
                                   textvariable=self._loot_max_var, width=4,
                                   font=("Segoe UI", 9), bg=LIGHT_BLUE, relief="flat",
                                   command=self._on_loot_delay_change)
        loot_max_spin.pack(side="left", padx=1)
        loot_max_spin.bind("<FocusOut>", lambda e: self._on_loot_delay_change())
        loot_max_spin.bind("<Return>", lambda e: self._on_loot_delay_change())

        tk.Label(toolbar, text="s", bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 9)).pack(side="left", padx=(0, 4))

        # Lure key
        tk.Label(toolbar, text="Lure:", bg=CARD_BG, fg=TEXT_DARK, font=("Segoe UI", 9)).pack(side="left", padx=(8, 2))
        self._lure_key_var = tk.StringVar(value=self._vk_to_label(self._lure_key) if self._lure_key else "-")
        lure_entry = tk.Entry(toolbar, textvariable=self._lure_key_var, width=3,
                              font=("Segoe UI", 11, "bold"), justify="center",
                              bg=LIGHT_BLUE, fg=TEXT_DARK, relief="flat", bd=2)
        lure_entry.pack(side="left", padx=2)
        lure_entry.bind("<FocusIn>", lambda e: self._lure_key_var.set(""))
        lure_entry.bind("<FocusOut>", lambda e: self._lure_key_var.set(
            self._vk_to_label(self._lure_key) if self._lure_key else "-"))
        lure_entry.bind("<KeyRelease>", self._on_lure_key_entry)

        # Status
        self._status_var = tk.StringVar(value="Idle")
        tk.Label(toolbar, textvariable=self._status_var, bg=CARD_BG, fg=TEXT_GREY,
                 font=("Segoe UI", 9)).pack(side="right", padx=6)

        # Split pane: fish stats (top) + log (bottom)
        split = tk.PanedWindow(left, orient="vertical", bg=CARD_BG, sashwidth=4, sashrelief="flat")
        split.grid(row=1, column=0, sticky="nsew")

        # ── Fish stats card ──
        fish_card = tk.Frame(split, bg=CARD_BG, relief="solid", bd=1)
        fish_card.columnconfigure(0, weight=1)
        fish_card.rowconfigure(1, weight=1)

        fish_header = tk.Frame(fish_card, bg=LIGHT_BLUE)
        fish_header.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._fish_header_label = tk.Label(fish_header, text="Fish Caught (0)",
                 bg=LIGHT_BLUE, fg=TEXT_DARK,
                 font=("Segoe UI", 9, "bold"), padx=6, pady=2)
        self._fish_header_label.pack(side="left")
        tk.Button(fish_header, text="Reset", bg=LIGHT_BLUE, fg=TEXT_DARK,
                  font=("Segoe UI", 7), relief="flat", bd=0, padx=4,
                  command=self._on_reset_fish).pack(side="right", padx=4)

        self._fish_text = tk.Text(fish_card, bg=BG_WHITE, fg=TEXT_DARK,
                                  font=("Consolas", 8), state="disabled", wrap="none",
                                  relief="flat", highlightthickness=0)
        fish_sb = tk.Scrollbar(fish_card, command=self._fish_text.yview, bg=BG_WHITE)
        self._fish_text.configure(yscrollcommand=fish_sb.set)
        fish_sb.grid(row=1, column=1, sticky="ns")
        self._fish_text.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)

        # Configure tag for percentage bars
        self._fish_text.tag_configure("bar", foreground=LIGHT_BLUE)
        self._fish_text.tag_configure("name", foreground=TEXT_DARK)
        self._fish_text.tag_configure("count", foreground=TEXT_GREY)

        split.add(fish_card, minsize=60)

        # ── Log card ──
        log_card = tk.Frame(split, bg=CARD_BG, relief="solid", bd=1)
        log_card.columnconfigure(0, weight=1)
        log_card.rowconfigure(1, weight=1)

        log_header = tk.Frame(log_card, bg=LIGHT_BLUE)
        log_header.grid(row=0, column=0, columnspan=2, sticky="ew")
        tk.Label(log_header, text="Log", bg=LIGHT_BLUE, fg=TEXT_DARK,
                 font=("Segoe UI", 9, "bold"), padx=6, pady=2).pack(anchor="w")

        self._log_text = tk.Text(log_card, bg=BG_WHITE, fg=TEXT_DARK,
                                 font=("Segoe UI", 8), state="disabled", wrap="word",
                                 relief="flat", highlightthickness=0)
        log_sb = tk.Scrollbar(log_card, command=self._log_text.yview, bg=BG_WHITE)
        self._log_text.configure(yscrollcommand=log_sb.set)
        log_sb.grid(row=1, column=1, sticky="ns")
        self._log_text.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)

        split.add(log_card, minsize=60)

        # ── CENTRE: screenshot ───────────────────────────────────────
        ss_frame = tk.Frame(main, bg="black", relief="solid", bd=1)
        ss_frame.grid(row=0, column=1, sticky="nsew", padx=2, pady=4)
        ss_frame.rowconfigure(0, weight=1)
        ss_frame.columnconfigure(0, weight=1)

        self._screenshot_canvas = tk.Canvas(ss_frame, bg="black", highlightthickness=0)
        self._screenshot_canvas.grid(row=0, column=0, sticky="nsew")
        self._ss_img_id = self._screenshot_canvas.create_image(0, 0, anchor="center")
        self._flying_fish = FlyingFishOverlay(self._screenshot_canvas)

        # Centre the image when canvas resizes
        self._screenshot_canvas.bind("<Configure>", self._on_ss_resize)

        self._loot_id_shadow = self._screenshot_canvas.create_text(0, 0, text="Looting...",
            font=("Segoe UI", 18, "bold"), fill=CHART_RED, anchor="center", state="hidden")
        self._loot_id = self._screenshot_canvas.create_text(0, 0, text="Looting...",
            font=("Segoe UI", 18, "bold"), fill="white", anchor="center", state="hidden")

        # ── RIGHT: chart ─────────────────────────────────────────────
        chart_card = tk.Frame(main, bg=CARD_BG, relief="solid", bd=1)
        chart_card.grid(row=0, column=2, sticky="nsew", padx=(2, 4), pady=4)
        chart_card.columnconfigure(0, weight=1)
        chart_card.rowconfigure(1, weight=1)

        chart_header = tk.Frame(chart_card, bg=LIGHT_BLUE)
        chart_header.grid(row=0, column=0, sticky="ew")
        tk.Label(chart_header, text="Bobber Amplitude", bg=LIGHT_BLUE,
                 fg=TEXT_DARK, font=("Segoe UI", 9, "bold"), padx=6, pady=2).pack(anchor="w")

        self._chart = BobberChart(chart_card, strike_value=STRIKE_VALUE)
        self._chart.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)

    def _on_ss_resize(self, event):
        # Keep image and loot text centred in canvas
        cx = event.width // 2
        cy = event.height // 2
        self._screenshot_canvas.coords(self._ss_img_id, cx, cy)
        self._screenshot_canvas.coords(self._loot_id_shadow, cx + 2, 32)
        self._screenshot_canvas.coords(self._loot_id, cx, 30)

    # ------------------------------------------------------------------
    # Logging bridge
    # ------------------------------------------------------------------

    def _setup_logging(self):
        handler = _QueueHandler(self._log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
        root_logger = logging.getLogger("Laksefisk")
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)

    def _append_log(self, text: str):
        self._log_text.configure(state="normal")
        self._log_text.insert("1.0", text + "\n")
        lines = int(self._log_text.index("end-1c").split(".")[0])
        if lines > 200:
            self._log_text.delete("150.0", "end")
        self._log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _poll(self):
        try:
            while True:
                msg = self._log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    # ------------------------------------------------------------------
    # Bot controls
    # ------------------------------------------------------------------

    def _on_play(self):
        if self._bot_thread and self._bot_thread.is_alive():
            return

        self._btn_play.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._status_var.set("Starting...")

        self._bot_thread = threading.Thread(target=self._bot_thread_func, daemon=True)
        self._bot_thread.start()

    def _on_stop(self):
        if self._bot:
            self._bot.stop()

    def _bot_thread_func(self):
        wow_process.press_key(0x20)  # VK_SPACE
        time.sleep(1.5)

        self.after(0, lambda: self._status_var.set("Running"))

        self._bot = LaksefiskBot(
            bobber_finder=self._bobber_finder,
            bite_watcher=self._bite_watcher,
            cast_key=self._cast_key,
            lure_key=self._lure_key,
            loot_wait_min=self._loot_min,
            loot_wait_max=self._loot_max,
        )
        self._bot.fishing_event_handler = self._on_fishing_event
        self._bot.start()

        self._bot = None
        self.after(0, self._on_bot_stopped)

    def _on_bot_stopped(self):
        self._btn_play.config(state="normal")
        self._btn_stop.config(state="disabled")
        self._status_var.set("Idle")
        self._flying_fish.stop()
        self._hide_loot()

    # ------------------------------------------------------------------
    # Fishing events
    # ------------------------------------------------------------------

    def _on_fishing_event(self, event: FishingEvent):
        self.after(0, lambda: self._handle_event(event))

    def _handle_event(self, event: FishingEvent):
        logger.info(str(event))

        if event.action == FishingAction.BobberMove:
            self._chart.add(event.amplitude)
        elif event.action == FishingAction.Loot:
            self._show_loot()
            self._flying_fish.start()
        elif event.action == FishingAction.Cast:
            self._chart.clear_chart()
            self._hide_loot()
            self._flying_fish.stop()

    def _show_loot(self):
        cw = self._screenshot_canvas.winfo_width()
        ch = self._screenshot_canvas.winfo_height()
        cx, cy = cw // 2, 30
        self._screenshot_canvas.coords(self._loot_id_shadow, cx + 2, cy + 2)
        self._screenshot_canvas.coords(self._loot_id, cx, cy)
        self._screenshot_canvas.itemconfigure(self._loot_id_shadow, state="normal")
        self._screenshot_canvas.itemconfigure(self._loot_id, state="normal")

    def _hide_loot(self):
        self._screenshot_canvas.itemconfigure(self._loot_id_shadow, state="hidden")
        self._screenshot_canvas.itemconfigure(self._loot_id, state="hidden")

    # ------------------------------------------------------------------
    # Fish stats
    # ------------------------------------------------------------------

    def _update_fish_display(self):
        stats = self._fish_tracker.get_stats()
        total = self._fish_tracker.total
        self._fish_header_label.config(text=f"Fish Caught ({total})")

        self._fish_text.configure(state="normal")
        self._fish_text.delete("1.0", "end")

        for name, count, pct in stats:
            # Visual bar: filled blocks proportional to percentage
            bar_len = int(pct / 5)  # max 20 blocks at 100%
            bar = "\u2588" * bar_len
            line = f" {name}"
            self._fish_text.insert("end", bar, "bar")
            self._fish_text.insert("end", f" {pct:4.1f}%  ", "count")
            self._fish_text.insert("end", f"{name}", "name")
            self._fish_text.insert("end", f"  x{count}\n", "count")

        self._fish_text.configure(state="disabled")

    def _on_reset_fish(self):
        self._fish_tracker.reset()

    # ------------------------------------------------------------------
    # Screenshot / bitmap event
    # ------------------------------------------------------------------

    def _on_bitmap_event(self, event: BobberBitmapEvent):
        if event.bitmap is None:
            return
        img = event.bitmap.copy()
        point = event.point
        self.after(0, lambda: self._update_screenshot(img, point))

    def _update_screenshot(self, img: Image.Image, point: Tuple[int, int]):
        if point != (0, 0):
            img = draw_reticle(img, point)

        cw = self._screenshot_canvas.winfo_width() or 500
        ch = self._screenshot_canvas.winfo_height() or 200

        # Scale to fill the canvas (cover, not letterbox)
        iw, ih = img.size
        scale = max(cw / iw, ch / ih)
        new_w = int(iw * scale)
        new_h = int(ih * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # Crop to canvas size from centre
        left = (new_w - cw) // 2
        top = (new_h - ch) // 2
        img = img.crop((left, top, left + cw, top + ch))

        self._screenshot_photo = ImageTk.PhotoImage(img)
        self._screenshot_canvas.itemconfig(self._ss_img_id, image=self._screenshot_photo)
        img.close()

    # ------------------------------------------------------------------
    # Key bind helpers
    # ------------------------------------------------------------------

    def _on_cast_key_entry(self, event):
        vk = self._keysym_to_vk(event.keysym)
        if vk:
            self._cast_key = vk
            self._cast_key_var.set(self._vk_to_label(vk))
            self._save_cfg()
            if self._bot:
                self._bot.set_cast_key(vk)
            self.focus()

    def _on_loot_delay_change(self):
        try:
            mn = self._loot_min_var.get()
            mx = self._loot_max_var.get()
        except tk.TclError:
            return
        mn = max(0.0, min(10.0, mn))
        mx = max(0.0, min(10.0, mx))
        if mx < mn:
            mx = mn
        self._loot_min_var.set(mn)
        self._loot_max_var.set(mx)
        self._loot_min = mn
        self._loot_max = mx
        self._save_cfg()
        if self._bot:
            self._bot.loot_wait_min = mn
            self._bot.loot_wait_max = mx

    def _on_lure_key_entry(self, event):
        vk = self._keysym_to_vk(event.keysym)
        if vk:
            self._lure_key = vk
            self._lure_key_var.set(self._vk_to_label(vk))
            self._save_cfg()
            if self._bot:
                self._bot.set_lure_key(vk)
            self.focus()

    def _keysym_to_vk(self, keysym: str) -> Optional[int]:
        if len(keysym) == 1 and keysym.isalnum():
            return ord(keysym.upper())
        mapping = {f"F{i+1}": 0x70 + i for i in range(12)}
        return mapping.get(keysym)

    def _vk_to_label(self, vk: int) -> str:
        if 0x30 <= vk <= 0x39:
            return chr(vk)
        if 0x41 <= vk <= 0x5A:
            return chr(vk)
        fkeys = {0x70 + i: f"F{i+1}" for i in range(12)}
        return fkeys.get(vk, f"0x{vk:02X}")

    def _save_cfg(self):
        self._cfg["cast_key"] = self._cast_key
        self._cfg["lure_key"] = self._lure_key
        self._cfg["loot_wait_min"] = self._loot_min
        self._cfg["loot_wait_max"] = self._loot_max
        self._cfg["colour_mode"] = "Red" if self._pc.mode == ClassifierMode.Red else "Blue"
        self._cfg["colour_multiplier"] = self._pc.colour_multiplier
        self._cfg["colour_closeness_multiplier"] = self._pc.colour_closeness_multiplier
        _save_config(self._cfg)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _on_settings(self):
        ColourConfigWindow(self, self._pc, on_change=self._save_cfg)


# ---------------------------------------------------------------------------
# Queue-based logging handler
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord):
        try:
            self._q.put_nowait(self.format(record))
        except queue.Full:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = App()
    app.mainloop()
