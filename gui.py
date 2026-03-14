"""
Laksefisk GUI — Dark-themed, dockable, resizable fishing bot interface.

Layout H (vertical): status bar → bobber view + amplitude overlay → fish list → log
Layout F (horizontal): status + bobber | fish | log (when docked top)

Docks to screen edges (left/top/right) or floats freely.
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

import mss
from PIL import Image, ImageDraw, ImageTk

import wow_process
from bite_watcher import PositionBiteWatcher
from bobber_calibration import sweep_calibrate
from bobber_finder import SearchBobberFinder
from fish_tracker import FishTracker
from fishing_bot import LaksefiskBot
from models import BobberBitmapEvent, FishingAction, FishingEvent
from pixel_bridge import PixelBridge
from pixel_classifier import ClassifierMode, PixelClassifier
from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_SCRIPT_DIR, "config.json")
LOOT_FILE = os.path.join(_SCRIPT_DIR, "loot.json")
STRIKE_VALUE = 7
_SNAP_THRESHOLD = 20

DEFAULT_CONFIG = {
    "cast_key": 0x34,
    "lure_key": None,
    "loot_wait_min": 0.5,
    "loot_wait_max": 2.0,
    "colour_mode": "Red",
    "colour_multiplier": 0.5,
    "colour_closeness_multiplier": 2.0,
    "dock_position": "floating",
    "window_width": 200,
    "window_height": 500,
    "horizontal_height": 110,
    "vertical_sash_positions": [120, 280],
    "horizontal_sash_positions": [130, 350],
    "log_collapsed": False,
    "bobber_zoom": 3.0,
    "always_on_top": True,
    "stop_on_player": False,
    "stop_on_bags": False,
    "auto_calibrate": False,
}

# Dark theme
BG_DARK = "#1a1a2e"
PANEL_BG = "#16213e"
PANEL_DEEP = "#0f3460"
ACCENT = "#00d4aa"
ALERT = "#e94560"
TEXT_PRIMARY = "#cccccc"
TEXT_DIM = "#555555"


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
# Amplitude overlay (draws on bobber view canvas)
# ---------------------------------------------------------------------------

class AmplitudeOverlay:
    """Draws amplitude bars as overlay on bottom 20% of a canvas."""

    def __init__(self, canvas: tk.Canvas, strike_value: int = 7):
        self._canvas = canvas
        self._strike = strike_value
        self._data: deque = deque(maxlen=120)
        self._item_ids: list = []

    def add(self, value: int):
        self._data.append((time.time(), value))
        self.draw()

    def clear_chart(self):
        self._data.clear()
        self.draw()

    def draw(self):
        for item_id in self._item_ids:
            self._canvas.delete(item_id)
        self._item_ids.clear()

        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 10 or h < 10:
            return

        overlay_h = int(h * 0.2)
        overlay_top = h - overlay_h

        bg_id = self._canvas.create_rectangle(
            0, overlay_top, w, h,
            fill=BG_DARK, stipple="gray50", outline=""
        )
        self._item_ids.append(bg_id)

        if len(self._data) < 2:
            return

        now = time.time()
        window = 20
        y_min, y_max = -15, 10
        y_range = y_max - y_min
        bar_w = 3

        for t, v in self._data:
            elapsed = now - t
            if elapsed > window:
                continue
            x = int(w - (elapsed / window) * w)
            norm = (v - y_min) / y_range
            bar_h = int(norm * overlay_h)
            bar_h = max(1, min(bar_h, overlay_h))

            colour = ALERT if v <= -self._strike else PANEL_DEEP
            bar_id = self._canvas.create_rectangle(
                x - bar_w, h - bar_h, x, h,
                fill=colour, outline=""
            )
            self._item_ids.append(bar_id)

        strike_norm = (-self._strike - y_min) / y_range
        strike_y = overlay_top + overlay_h - int(strike_norm * overlay_h)
        if overlay_top <= strike_y <= h:
            line_id = self._canvas.create_line(
                0, strike_y, w, strike_y,
                fill=TEXT_DIM, dash=(4, 4)
            )
            self._item_ids.append(line_id)


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
# Tooltip
# ---------------------------------------------------------------------------

class _Tooltip:
    """Hover tooltip for any widget."""

    def __init__(self, widget: tk.Widget, text: str):
        self._widget = widget
        self.text = text
        self._tw = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _e):
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tw = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw, text=self.text, justify="left", bg="#ffffe0", fg="#333",
                 relief="solid", bd=1, font=("Segoe UI", 8),
                 padx=6, pady=4, wraplength=300).pack()

    def _hide(self, _e):
        if self._tw:
            self._tw.destroy()
            self._tw = None


# ---------------------------------------------------------------------------
# Settings Popup
# ---------------------------------------------------------------------------

class SettingsPopup(tk.Toplevel):
    """Unified settings popup — dark themed."""

    def __init__(self, parent: "App", on_change: callable):
        super().__init__(parent)
        self.title("Settings")
        self.configure(bg=BG_DARK)
        self.geometry("420x600")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self._parent = parent
        self._on_change = on_change
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        if hasattr(self, "_live_timer") and self._live_timer:
            self.after_cancel(self._live_timer)
        self.destroy()

    def _build(self):
        container = tk.Frame(self, bg=BG_DARK, padx=12, pady=8)
        container.pack(fill="both", expand=True)

        row = 0
        # --- Cast Key ---
        self._add_label(container, "Cast Key", row)
        self._cast_var = tk.StringVar(value=self._parent._vk_to_label(self._parent._cast_key))
        e = tk.Entry(
            container, textvariable=self._cast_var, bg=PANEL_BG,
            fg=TEXT_PRIMARY, font=("Consolas", 10), insertbackground=TEXT_PRIMARY,
            relief="flat", width=8
        )
        e.grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        e.bind("<FocusIn>", lambda _: self._cast_var.set(""))
        e.bind("<FocusOut>", lambda _: self._cast_var.set(
            self._parent._vk_to_label(self._parent._cast_key)))
        e.bind("<KeyRelease>", self._on_cast_key)
        row += 1

        # --- Lure Key ---
        self._add_label(container, "Lure Key", row)
        lure = self._parent._lure_key
        self._lure_var = tk.StringVar(
            value=self._parent._vk_to_label(lure) if lure else "-")
        e = tk.Entry(
            container, textvariable=self._lure_var, bg=PANEL_BG,
            fg=TEXT_PRIMARY, font=("Consolas", 10), insertbackground=TEXT_PRIMARY,
            relief="flat", width=8
        )
        e.grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        e.bind("<FocusIn>", lambda _: self._lure_var.set(""))
        e.bind("<FocusOut>", lambda _: self._lure_var.set(
            self._parent._vk_to_label(self._parent._lure_key) if self._parent._lure_key else "-"))
        e.bind("<KeyRelease>", self._on_lure_key)
        row += 1

        # --- Loot Wait ---
        self._add_label(container, "Loot Wait Min (s)", row)
        self._loot_min_var = tk.DoubleVar(value=self._parent._loot_min)
        tk.Scale(
            container, variable=self._loot_min_var, from_=0.0, to=10.0,
            resolution=0.1, orient="horizontal", bg=PANEL_BG, fg=TEXT_PRIMARY,
            troughcolor=PANEL_DEEP, highlightthickness=0,
            command=lambda _: self._on_loot_change()
        ).grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        row += 1

        self._add_label(container, "Loot Wait Max (s)", row)
        self._loot_max_var = tk.DoubleVar(value=self._parent._loot_max)
        tk.Scale(
            container, variable=self._loot_max_var, from_=0.0, to=10.0,
            resolution=0.1, orient="horizontal", bg=PANEL_BG, fg=TEXT_PRIMARY,
            troughcolor=PANEL_DEEP, highlightthickness=0,
            command=lambda _: self._on_loot_change()
        ).grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        row += 1

        # --- Separator ---
        ttk.Separator(container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
        row += 1

        # --- Colour Mode ---
        self._add_label(container, "Colour Mode", row)
        mode_frame = tk.Frame(container, bg=BG_DARK)
        mode_frame.grid(row=row, column=1, sticky="w", pady=2, padx=(4, 0))
        self._mode_var = tk.StringVar(
            value="Red" if self._parent._pc.mode == ClassifierMode.Red else "Blue"
        )
        for mode in ("Red", "Blue"):
            tk.Radiobutton(
                mode_frame, text=mode, variable=self._mode_var, value=mode,
                bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
                activebackground=BG_DARK, activeforeground=ACCENT,
                command=self._on_mode_change
            ).pack(side="left", padx=(0, 8))
        row += 1

        # --- Colour Multiplier ---
        self._add_label(container, "Colour Multiplier", row)
        self._mult_var = tk.DoubleVar(value=self._parent._pc.colour_multiplier)
        tk.Scale(
            container, variable=self._mult_var, from_=0.0, to=3.0,
            resolution=0.05, orient="horizontal", bg=PANEL_BG, fg=TEXT_PRIMARY,
            troughcolor=PANEL_DEEP, highlightthickness=0,
            command=lambda _: self._on_mult_change()
        ).grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        row += 1

        # --- Colour Closeness ---
        self._add_label(container, "Colour Closeness", row)
        self._close_var = tk.DoubleVar(
            value=self._parent._pc.colour_closeness_multiplier
        )
        tk.Scale(
            container, variable=self._close_var, from_=0.0, to=5.0,
            resolution=0.1, orient="horizontal", bg=PANEL_BG, fg=TEXT_PRIMARY,
            troughcolor=PANEL_DEEP, highlightthickness=0,
            command=lambda _: self._on_close_change()
        ).grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        row += 1

        # --- Separator ---
        ttk.Separator(container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
        row += 1

        # --- Checkboxes ---
        self._auto_cal_var = tk.BooleanVar(
            value=self._parent._cfg.get("auto_calibrate", False)
        )
        tk.Checkbutton(
            container, text="Auto-calibrate on start", variable=self._auto_cal_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=BG_DARK, activeforeground=ACCENT,
            command=self._on_auto_cal
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._stop_player_var = tk.BooleanVar(
            value=self._parent._cfg.get("stop_on_player", False)
        )
        tk.Checkbutton(
            container, text="Stop on player nearby", variable=self._stop_player_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=BG_DARK, activeforeground=ACCENT,
            command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._stop_bags_var = tk.BooleanVar(
            value=self._parent._cfg.get("stop_on_bags", False)
        )
        tk.Checkbutton(
            container, text="Stop on bags full", variable=self._stop_bags_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=BG_DARK, activeforeground=ACCENT,
            command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._topmost_var = tk.BooleanVar(
            value=self._parent._cfg.get("always_on_top", True)
        )
        tk.Checkbutton(
            container, text="Always on top", variable=self._topmost_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=BG_DARK, activeforeground=ACCENT,
            command=self._on_topmost
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        # --- Separator ---
        ttk.Separator(container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
        row += 1

        # --- Dock Position ---
        self._add_label(container, "Dock Position", row)
        self._dock_var = tk.StringVar(value=self._parent._dock_mode)
        dock_menu = ttk.Combobox(
            container, textvariable=self._dock_var,
            values=["left", "top", "right", "floating"],
            state="readonly", width=10
        )
        dock_menu.grid(row=row, column=1, sticky="w", pady=2, padx=(4, 0))
        dock_menu.bind("<<ComboboxSelected>>", self._on_dock_change)
        row += 1

        # --- Reset ---
        tk.Button(
            container, text="Reset to Defaults", bg=ALERT, fg="white",
            font=("Consolas", 9), relief="flat", padx=8, pady=4,
            command=self._on_reset, cursor="hand2"
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(12, 0))
        row += 1

        # --- Separator ---
        ttk.Separator(container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
        row += 1

        # --- Expandable: Colour Preview ---
        self._preview_expanded = False
        self._preview_btn = tk.Button(
            container, text="\u25b6 Colour Preview", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 9), relief="flat", anchor="w",
            command=self._toggle_preview, cursor="hand2"
        )
        self._preview_btn.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 0))
        row += 1

        self._preview_frame = tk.Frame(container, bg=BG_DARK)
        self._preview_row = row

        btn_row = tk.Frame(self._preview_frame, bg=BG_DARK)
        btn_row.pack(fill="x", pady=4)
        tk.Button(
            btn_row, text="Capture", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
            font=("Consolas", 8), relief="flat", padx=6,
            command=self._on_capture
        ).pack(side="left", padx=(0, 4))
        self._live_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            btn_row, text="Live", variable=self._live_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            command=self._toggle_live
        ).pack(side="left")
        self._match_label = tk.Label(
            btn_row, text="Matches: \u2014", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 8)
        )
        self._match_label.pack(side="right")

        self._preview_canvas = tk.Canvas(
            self._preview_frame, bg="black", width=380, height=180,
            highlightthickness=0
        )
        self._preview_canvas.pack(fill="both", expand=True)
        self._preview_img_id = self._preview_canvas.create_image(0, 0, anchor="nw")
        self._preview_photo = None
        self._live_timer = None

        container.columnconfigure(1, weight=1)

    def _add_label(self, parent, text, row):
        tk.Label(
            parent, text=text, bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 9), anchor="w"
        ).grid(row=row, column=0, sticky="w", pady=2)

    def _toggle_preview(self):
        self._preview_expanded = not self._preview_expanded
        if self._preview_expanded:
            self._preview_btn.config(text="\u25bc Colour Preview")
            self._preview_frame.grid(
                row=self._preview_row, column=0, columnspan=2,
                sticky="nsew", pady=4
            )
        else:
            self._preview_btn.config(text="\u25b6 Colour Preview")
            self._preview_frame.grid_forget()
            if self._live_timer:
                self.after_cancel(self._live_timer)
                self._live_timer = None
                self._live_var.set(False)

    def _on_capture(self):
        self._render_preview()

    def _toggle_live(self):
        if self._live_var.get():
            self._live_update()
        else:
            if self._live_timer:
                self.after_cancel(self._live_timer)
                self._live_timer = None

    def _live_update(self):
        self._render_preview()
        self._live_timer = self.after(500, self._live_update)

    def _render_preview(self):
        """Capture screen and render matched pixels."""
        try:
            img = WowScreen.get_bitmap()
            pc = self._parent._pc
            iw, ih = img.size
            pixels = img.load()
            matches = 0
            highlight = (0, 0, 255) if pc.mode == ClassifierMode.Blue else (255, 0, 0)
            for y in range(0, ih, 2):
                for x in range(0, iw, 2):
                    r, g, b = pixels[x, y][:3]
                    if pc.is_match(r, g, b):
                        matches += 1
                        pixels[x, y] = highlight
            self._match_label.config(text=f"Matches: {matches}")
            cw, ch = 380, 180
            img = img.resize((cw, ch), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(img)
            self._preview_canvas.itemconfig(self._preview_img_id, image=self._preview_photo)
        except Exception as e:
            self._match_label.config(text=f"Error: {e}")

    def _on_cast_key(self, event):
        vk = self._parent._keysym_to_vk(event.keysym)
        if vk:
            self._parent._cast_key = vk
            self._cast_var.set(self._parent._vk_to_label(vk))
            if self._parent._bot:
                self._parent._bot.set_cast_key(vk)
            self._parent._save_cfg()

    def _on_lure_key(self, event):
        vk = self._parent._keysym_to_vk(event.keysym)
        if vk:
            self._parent._lure_key = vk
            self._lure_var.set(self._parent._vk_to_label(vk))
            if self._parent._bot:
                self._parent._bot.set_lure_key(vk)
            self._parent._save_cfg()

    def _on_loot_change(self):
        self._parent._loot_min = self._loot_min_var.get()
        self._parent._loot_max = max(
            self._loot_max_var.get(), self._parent._loot_min
        )
        if self._parent._bot:
            self._parent._bot.loot_wait_min = self._parent._loot_min
            self._parent._bot.loot_wait_max = self._parent._loot_max
        self._parent._save_cfg()

    def _on_mode_change(self):
        mode = ClassifierMode.Red if self._mode_var.get() == "Red" else ClassifierMode.Blue
        self._parent._pc.mode = mode
        self._parent._save_cfg()
        self._on_change()

    def _on_mult_change(self):
        self._parent._pc.colour_multiplier = self._mult_var.get()
        self._parent._save_cfg()
        self._on_change()

    def _on_close_change(self):
        self._parent._pc.colour_closeness_multiplier = self._close_var.get()
        self._parent._save_cfg()
        self._on_change()

    def _on_auto_cal(self):
        self._parent._cfg["auto_calibrate"] = self._auto_cal_var.get()
        if self._parent._bot:
            self._parent._bot.auto_calibrate = self._auto_cal_var.get()
        self._parent._save_cfg()

    def _on_stop_conditions(self):
        self._parent._cfg["stop_on_player"] = self._stop_player_var.get()
        self._parent._cfg["stop_on_bags"] = self._stop_bags_var.get()
        if self._parent._bot:
            self._parent._bot.stop_on_player_nearby = self._stop_player_var.get()
            self._parent._bot.stop_on_bags_full = self._stop_bags_var.get()
        self._parent._save_cfg()

    def _on_topmost(self):
        val = self._topmost_var.get()
        self._parent._cfg["always_on_top"] = val
        self._parent.attributes("-topmost", val)
        self._parent._save_cfg()

    def _on_dock_change(self, _event=None):
        dock = self._dock_var.get()
        self._parent._apply_dock(dock)
        self._parent._save_cfg()

    def _on_reset(self):
        for key, val in DEFAULT_CONFIG.items():
            self._parent._cfg[key] = val
        self._parent._cast_key = DEFAULT_CONFIG["cast_key"]
        self._parent._lure_key = DEFAULT_CONFIG["lure_key"]
        self._parent._loot_min = DEFAULT_CONFIG["loot_wait_min"]
        self._parent._loot_max = DEFAULT_CONFIG["loot_wait_max"]
        mode = ClassifierMode.Red if DEFAULT_CONFIG["colour_mode"] == "Red" else ClassifierMode.Blue
        self._parent._pc.mode = mode
        self._parent._pc.colour_multiplier = DEFAULT_CONFIG["colour_multiplier"]
        self._parent._pc.colour_closeness_multiplier = DEFAULT_CONFIG["colour_closeness_multiplier"]
        self._parent._save_cfg()
        self.destroy()
        self._parent._on_settings()


# ---------------------------------------------------------------------------
# Main Application Window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        # mss DPI warm-up — MUST be before any geometry calls.
        # mss.mss() changes Windows DPI awareness on first call, which would
        # resize the tkinter window if called later.
        with mss.mss():
            pass

        self._cfg = _load_config()
        self.title("Laksefisk")
        self.configure(bg=BG_DARK)

        # Window geometry from config
        dock = self._cfg.get("dock_position", "floating")
        w = self._cfg.get("window_width", 200)
        h = self._cfg.get("window_height", 500)
        self.geometry(f"{w}x{h}")
        self.minsize(160, 300)

        # Always on top
        if self._cfg.get("always_on_top", True):
            self.attributes("-topmost", True)

        # Dock mode tracking
        self._dock_mode = dock
        self._layout_mode = "horizontal" if dock == "top" else "vertical"
        self._configure_after_id = None

        # Core components
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
        self._is_running = False

        # Fish tracker (pixel bridge mode)
        self._fish_tracker = FishTracker(loot_file=LOOT_FILE)
        self._fish_tracker.load_loot()
        self._fish_tracker.set_on_update(lambda: self.after(0, self._update_fish_display))

        # Pixel bridge (replaces OCR for loot detection)
        self._pixel_bridge = PixelBridge()

        self._bobber_finder.bitmap_callbacks.append(self._on_bitmap_event)

        self._build_ui()
        self._setup_logging()
        self._poll()
        self._check_addon_status()

        # Apply initial dock position
        if dock != "floating":
            self.after(100, lambda: self._apply_dock(dock))

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------

    def _build_ui(self):
        """Build adaptive layout — vertical stack or horizontal row."""
        self._main_frame = tk.Frame(self, bg=BG_DARK)
        self._main_frame.pack(fill="both", expand=True)

        # Status bar (always at top)
        self._build_status_bar()

        # PanedWindow for resizable panels
        orient = "horizontal" if self._layout_mode == "horizontal" else "vertical"
        self._paned = ttk.PanedWindow(self._main_frame, orient=orient)
        self._paned.pack(fill="both", expand=True, padx=2, pady=2)

        # Build panels
        self._build_bobber_view()
        self._build_fish_list()
        self._build_log_panel()

        # Add panels to paned window
        self._paned.add(self._bobber_frame, weight=3)
        self._paned.add(self._fish_frame, weight=2)
        self._log_collapsed = self._cfg.get("log_collapsed", False)
        if not self._log_collapsed:
            self._paned.add(self._log_frame, weight=1)

        # Restore sash positions
        self._restore_sash_positions()

        # Bind resize for dock detection
        self.bind("<Configure>", self._on_configure)

        # Save config on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_status_bar(self):
        bar = tk.Frame(self._main_frame, bg=BG_DARK, pady=4, padx=4)
        bar.pack(fill="x")

        # Play/stop toggle — canvas-drawn circle
        self._toggle_canvas = tk.Canvas(
            bar, width=24, height=24, bg=BG_DARK,
            highlightthickness=0, cursor="hand2"
        )
        self._toggle_canvas.pack(side="left", padx=(0, 4))
        self._toggle_canvas.bind("<Button-1>", self._on_toggle)
        self._draw_toggle()

        # Status text
        self._status_var = tk.StringVar(value="Idle")
        self._status_label = tk.Label(
            bar, textvariable=self._status_var, bg=BG_DARK,
            fg=ACCENT, font=("Consolas", 9)
        )
        self._status_label.pack(side="left", padx=(0, 4))

        # Addon dot
        self._addon_canvas = tk.Canvas(
            bar, width=10, height=10, bg=BG_DARK, highlightthickness=0
        )
        self._addon_canvas.pack(side="left", padx=(0, 4))
        self._addon_dot = self._addon_canvas.create_oval(1, 1, 9, 9, fill=TEXT_DIM)
        self._addon_tooltip = _Tooltip(self._addon_canvas, "Addon: Not found")

        # Spacer
        tk.Frame(bar, bg=BG_DARK).pack(side="left", fill="x", expand=True)

        # Cal button
        self._cal_btn = tk.Button(
            bar, text="Cal", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
            font=("Consolas", 8), relief="flat", padx=4, pady=1,
            command=self._on_calibrate, cursor="hand2"
        )
        self._cal_btn.pack(side="left", padx=(0, 4))
        _Tooltip(self._cal_btn, "Calibrate bobber detection")

        # Gear icon
        tk.Button(
            bar, text="\u2699", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 12), relief="flat", bd=0,
            command=self._on_settings, cursor="hand2"
        ).pack(side="left")

    def _draw_toggle(self):
        self._toggle_canvas.delete("all")
        if self._is_running:
            self._toggle_canvas.create_oval(2, 2, 22, 22, fill=ALERT, outline="")
            self._toggle_canvas.create_rectangle(8, 8, 16, 16, fill=BG_DARK, outline="")
        else:
            self._toggle_canvas.create_oval(2, 2, 22, 22, fill=ACCENT, outline="")
            self._toggle_canvas.create_polygon(
                10, 7, 10, 17, 18, 12, fill=BG_DARK, outline=""
            )

    def _on_toggle(self, _event=None):
        if self._is_running:
            self._on_stop()
        else:
            self._on_play()

    def _build_bobber_view(self):
        self._bobber_frame = tk.Frame(self._paned, bg="black")
        self._screenshot_canvas = tk.Canvas(
            self._bobber_frame, bg="black", highlightthickness=0
        )
        self._screenshot_canvas.pack(fill="both", expand=True)
        self._ss_img_id = self._screenshot_canvas.create_image(0, 0, anchor="center")
        self._screenshot_photo = None

        # Amplitude overlay (draws on same canvas)
        self._amplitude = AmplitudeOverlay(self._screenshot_canvas, STRIKE_VALUE)

        # Flying fish overlay
        self._flying_fish = FlyingFishOverlay(self._screenshot_canvas)

        # Loot text overlay
        self._loot_id_shadow = self._screenshot_canvas.create_text(
            0, 32, text="Looting...", fill=BG_DARK,
            font=("Consolas", 14, "bold"), anchor="n", state="hidden"
        )
        self._loot_id = self._screenshot_canvas.create_text(
            0, 30, text="Looting...", fill=TEXT_PRIMARY,
            font=("Consolas", 14, "bold"), anchor="n", state="hidden"
        )

        self._screenshot_canvas.bind("<Configure>", self._on_ss_resize)

    def _build_fish_list(self):
        self._fish_frame = tk.Frame(self._paned, bg=PANEL_BG)

        # Header
        header = tk.Frame(self._fish_frame, bg=PANEL_BG, pady=2, padx=4)
        header.pack(fill="x")
        self._fish_header_label = tk.Label(
            header, text="Fish Caught (0)", bg=PANEL_BG,
            fg=ACCENT, font=("Consolas", 9, "bold"), anchor="w"
        )
        self._fish_header_label.pack(side="left")
        tk.Button(
            header, text="\u21bb", bg=PANEL_BG, fg=TEXT_DIM,
            font=("Consolas", 10), relief="flat", bd=0,
            command=self._on_reset_fish, cursor="hand2"
        ).pack(side="right")

        # Fish text widget
        self._fish_text = tk.Text(
            self._fish_frame, bg=PANEL_BG, fg=TEXT_PRIMARY,
            font=("Consolas", 9), wrap="none", state="disabled",
            relief="flat", bd=0, padx=4, pady=2,
            selectbackground=PANEL_DEEP, insertbackground=TEXT_PRIMARY
        )
        self._fish_text.pack(fill="both", expand=True)
        self._fish_text.tag_configure("bar", foreground=PANEL_DEEP)
        self._fish_text.tag_configure("name", foreground=TEXT_PRIMARY)
        self._fish_text.tag_configure("count", foreground=TEXT_DIM)

    def _build_log_panel(self):
        self._log_frame = tk.Frame(self._paned, bg=PANEL_BG)

        # Header
        header = tk.Frame(self._log_frame, bg=PANEL_BG, pady=2, padx=4)
        header.pack(fill="x")
        tk.Label(
            header, text="Log", bg=PANEL_BG, fg=TEXT_DIM,
            font=("Consolas", 9)
        ).pack(side="left")
        self._log_chevron = tk.Label(
            header, text="\u25b2" if self._cfg.get("log_collapsed", False) else "\u25bc",
            bg=PANEL_BG, fg=TEXT_DIM, font=("Consolas", 8), cursor="hand2"
        )
        self._log_chevron.pack(side="right")
        self._log_chevron.bind("<Button-1>", self._toggle_log)

        # Log text widget
        self._log_text = tk.Text(
            self._log_frame, bg=PANEL_BG, fg=TEXT_PRIMARY,
            font=("Consolas", 8), wrap="word", state="disabled",
            relief="flat", bd=0, padx=4, pady=2,
            selectbackground=PANEL_DEEP, insertbackground=TEXT_PRIMARY
        )
        self._log_text.pack(fill="both", expand=True)

    def _toggle_log(self, _event=None):
        self._log_collapsed = not self._log_collapsed
        self._log_chevron.config(
            text="\u25b2" if self._log_collapsed else "\u25bc"
        )
        if self._log_collapsed:
            self._paned.forget(self._log_frame)
        else:
            self._paned.add(self._log_frame, weight=1)
        self._save_cfg()

    # ------------------------------------------------------------------
    # Screenshot / bitmap
    # ------------------------------------------------------------------

    def _on_ss_resize(self, event):
        cx = event.width // 2
        self._screenshot_canvas.coords(self._ss_img_id, cx, event.height // 2)
        self._screenshot_canvas.coords(self._loot_id_shadow, cx + 2, 32)
        self._screenshot_canvas.coords(self._loot_id, cx, 30)

    def _on_bitmap_event(self, event: BobberBitmapEvent):
        if event.bitmap is None:
            return
        img = event.bitmap.copy()
        point = event.point
        self.after(0, lambda: self._update_screenshot(img, point))

    def _update_screenshot(self, img: Image.Image, point: Tuple[int, int]):
        if point != (0, 0):
            # Zoom: crop around bobber position before display
            iw, ih = img.size
            zoom = self._cfg.get("bobber_zoom", 3.0)
            crop_w = int(iw / zoom)
            crop_h = int(ih / zoom)
            cx, cy = point
            x1 = max(0, cx - crop_w // 2)
            y1 = max(0, cy - crop_h // 2)
            x2 = min(iw, x1 + crop_w)
            y2 = min(ih, y1 + crop_h)
            x1 = max(0, x2 - crop_w)
            y1 = max(0, y2 - crop_h)
            img = img.crop((x1, y1, x2, y2))
            reticle_x = cx - x1
            reticle_y = cy - y1
            img = draw_reticle(img, (reticle_x, reticle_y))
        else:
            img = draw_reticle(img, point)

        cw = self._screenshot_canvas.winfo_width() or 500
        ch = self._screenshot_canvas.winfo_height() or 200
        if cw < 10 or ch < 10:
            return

        iw, ih = img.size
        scale = min(cw / iw, ch / ih)
        new_w = max(1, int(iw * scale))
        new_h = max(1, int(ih * scale))
        img = img.resize((new_w, new_h), Image.LANCZOS)
        self._screenshot_photo = ImageTk.PhotoImage(img)
        self._screenshot_canvas.coords(self._ss_img_id, cw // 2, ch // 2)
        self._screenshot_canvas.itemconfig(self._ss_img_id, image=self._screenshot_photo)

        # Redraw amplitude overlay on top
        self._amplitude.draw()

    # ------------------------------------------------------------------
    # Dock detection and layout switching
    # ------------------------------------------------------------------

    def _on_configure(self, event=None):
        if event and event.widget != self:
            return
        if self._configure_after_id:
            self.after_cancel(self._configure_after_id)
        self._configure_after_id = self.after(100, self._check_dock)

    def _check_dock(self):
        self._configure_after_id = None
        x = self.winfo_x()
        y = self.winfo_y()
        w = self.winfo_width()
        sw = self.winfo_screenwidth()

        old_mode = self._layout_mode

        if y <= _SNAP_THRESHOLD:
            new_dock = "top"
            new_layout = "horizontal"
        elif x <= _SNAP_THRESHOLD:
            new_dock = "left"
            new_layout = "vertical"
        elif x + w >= sw - _SNAP_THRESHOLD:
            new_dock = "right"
            new_layout = "vertical"
        else:
            new_dock = "floating"
            new_layout = self._layout_mode

        self._dock_mode = new_dock

        if new_layout != old_mode:
            self._layout_mode = new_layout
            self._rebuild_layout()

    def _rebuild_layout(self):
        """Destroy and rebuild paned window with new orientation."""
        self._save_sash_positions()
        self._paned.destroy()

        if self._layout_mode == "horizontal":
            self._paned = ttk.PanedWindow(self._main_frame, orient="horizontal")
            self.minsize(400, 90)
        else:
            self._paned = ttk.PanedWindow(self._main_frame, orient="vertical")
            self.minsize(160, 300)

        self._paned.pack(fill="both", expand=True, padx=2, pady=2)

        # Recreate panel frames inside new paned window
        self._build_bobber_view()
        self._build_fish_list()
        self._build_log_panel()

        self._paned.add(self._bobber_frame, weight=3)
        self._paned.add(self._fish_frame, weight=2)
        if not self._log_collapsed:
            self._paned.add(self._log_frame, weight=1)

        self._restore_sash_positions()
        self._update_fish_display()

    def _apply_dock(self, dock: str):
        """Move window to dock position."""
        self._dock_mode = dock
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = self._cfg.get("window_width", 200)
        h = self._cfg.get("window_height", 500)

        old_mode = self._layout_mode

        if dock == "left":
            self._layout_mode = "vertical"
            self.geometry(f"{w}x{sh}+0+0")
        elif dock == "right":
            self._layout_mode = "vertical"
            self.geometry(f"{w}x{sh}+{sw - w}+0")
        elif dock == "top":
            self._layout_mode = "horizontal"
            hh = self._cfg.get("horizontal_height", 110)
            self.geometry(f"{sw}x{hh}+0+0")
        else:
            self._layout_mode = "vertical"
            self.geometry(f"{w}x{h}")

        if old_mode != self._layout_mode:
            self._rebuild_layout()

    def _save_sash_positions(self):
        try:
            n = len(self._paned.panes()) - 1
            positions = [self._paned.sashpos(i) for i in range(n)]
            key = f"{self._layout_mode}_sash_positions"
            self._cfg[key] = positions
        except Exception:
            pass

    def _restore_sash_positions(self):
        key = f"{self._layout_mode}_sash_positions"
        positions = self._cfg.get(key)
        if positions:
            self.after(50, lambda: self._apply_sash_positions(positions))

    def _apply_sash_positions(self, positions):
        try:
            n = len(self._paned.panes()) - 1
            for i, pos in enumerate(positions):
                if i < n:
                    self._paned.sashpos(i, pos)
        except Exception:
            pass

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
        self._is_running = True
        self._draw_toggle()
        self._status_var.set("Starting...")
        self._amplitude.clear_chart()
        self._bot_thread = threading.Thread(target=self._bot_thread_func, daemon=True)
        self._bot_thread.start()

    def _on_stop(self):
        if self._bot:
            self._bot.stop()

    def _on_calibrate(self):
        """One-time sweep calibration from current screen."""
        def _run():
            success = sweep_calibrate(self._pc)
            if success:
                self.after(0, lambda: self._status_var.set(
                    f"Cal: m={self._pc.colour_multiplier:.2f} "
                    f"c={self._pc.colour_closeness_multiplier:.1f}"))
                self.after(0, self._save_cfg)
            else:
                self.after(0, lambda: self._status_var.set("Calibration failed"))
        threading.Thread(target=_run, daemon=True).start()

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
        self._bot.fish_tracker = self._fish_tracker
        self._bot.pixel_bridge = self._pixel_bridge
        self._bot.stop_on_player_nearby = self._cfg.get("stop_on_player", False)
        self._bot.stop_on_bags_full = self._cfg.get("stop_on_bags", False)
        self._bot.auto_calibrate = self._cfg.get("auto_calibrate", False)
        self._bot._pixel_classifier = self._pc
        self._bot.start()

        self._bot = None
        self.after(0, self._on_bot_stopped)

    def _on_bot_stopped(self):
        self._is_running = False
        self._draw_toggle()
        self._status_var.set("Idle")
        self._flying_fish.stop()
        self._hide_loot()

    # ------------------------------------------------------------------
    # Fishing events
    # ------------------------------------------------------------------

    def _on_fishing_event(self, event: FishingEvent):
        self.after(0, lambda: self._handle_event(event))

    def _handle_event(self, event: FishingEvent):
        if event.action == FishingAction.BobberMove:
            self._amplitude.add(event.amplitude)
        elif event.action == FishingAction.Loot:
            self._show_loot()
            self._flying_fish.start()
        elif event.action == FishingAction.Cast:
            self._amplitude.clear_chart()
            self._hide_loot()
            self._flying_fish.stop()

    def _show_loot(self):
        cw = self._screenshot_canvas.winfo_width()
        cx = cw // 2
        self._screenshot_canvas.coords(self._loot_id_shadow, cx + 2, 32)
        self._screenshot_canvas.coords(self._loot_id, cx, 30)
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
            bar_len = int(pct / 5)
            bar = "\u2588" * bar_len
            self._fish_text.insert("end", bar, "bar")
            self._fish_text.insert("end", f" {pct:4.1f}%  ", "count")
            self._fish_text.insert("end", f"{name}", "name")
            self._fish_text.insert("end", f"  x{count}\n", "count")

        self._fish_text.configure(state="disabled")

    def _on_reset_fish(self):
        self._fish_tracker.reset()

    def _check_addon_status(self):
        try:
            data = self._pixel_bridge.read()
            connected = data is not None
        except Exception:
            connected = False

        colour = ACCENT if connected else TEXT_DIM
        self._addon_canvas.itemconfig(self._addon_dot, fill=colour)
        self._addon_tooltip.text = "Addon: Connected" if connected else "Addon: Not found"

        self.after(2000, self._check_addon_status)

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _save_cfg(self):
        self._cfg["cast_key"] = self._cast_key
        self._cfg["lure_key"] = self._lure_key
        self._cfg["loot_wait_min"] = self._loot_min
        self._cfg["loot_wait_max"] = self._loot_max
        self._cfg["colour_mode"] = "Red" if self._pc.mode == ClassifierMode.Red else "Blue"
        self._cfg["colour_multiplier"] = self._pc.colour_multiplier
        self._cfg["colour_closeness_multiplier"] = self._pc.colour_closeness_multiplier
        self._cfg["dock_position"] = self._dock_mode
        self._cfg["log_collapsed"] = self._log_collapsed
        self._cfg["always_on_top"] = bool(self.attributes("-topmost"))
        self._cfg["window_width"] = self.winfo_width()
        self._cfg["window_height"] = self.winfo_height()
        self._save_sash_positions()
        _save_config(self._cfg)

    def _on_close(self):
        self._save_cfg()
        if self._bot:
            self._bot.stop()
        self.destroy()

    def _on_settings(self):
        SettingsPopup(self, on_change=lambda: None)


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
