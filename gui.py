"""
Laksefisk GUI — Dark-themed, resizable fishing bot interface.

Layout: status bar → bobber view + amplitude overlay → fish list → log (vertical stack)
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
import webbrowser
import winsound
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

DEFAULT_CONFIG = {
    "cast_key": 0x34,
    "lure_key": None,
    "loot_wait_min": 0.5,
    "loot_wait_max": 2.0,
    "colour_mode": "Red",
    "colour_multiplier": 0.5,
    "colour_closeness_multiplier": 2.0,
    "window_width": 200,
    "window_height": 500,
    "sash_positions": [120, 280],
    "log_collapsed": False,
    "bobber_zoom": 3.0,
    "always_on_top": True,
    "stop_on_player": False,
    "stop_on_bags": False,
    "auto_delete_junk": False,
    "auto_calibrate": False,
    "bite_sensitivity": 7,
    "sound_alerts": False,
    "pixel_bar_region": None,
    "container_key": None,
    "auto_open_containers": False,
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
        self.transient(parent)
        self.grab_set()
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

        # --- Bite Sensitivity ---
        self._add_label(container, "Bite Sensitivity", row)
        self._bite_var = tk.IntVar(value=self._parent._bite_sensitivity)
        tk.Scale(
            container, variable=self._bite_var, from_=1, to=20,
            resolution=1, orient="horizontal", bg=PANEL_BG, fg=TEXT_PRIMARY,
            troughcolor=PANEL_DEEP, highlightthickness=0,
            command=lambda _: self._on_bite_change()
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

        self._auto_delete_var = tk.BooleanVar(
            value=self._parent._cfg.get("auto_delete_junk", False)
        )
        tk.Checkbutton(
            container, text="Auto-delete junk", variable=self._auto_delete_var,
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

        self._sound_var = tk.BooleanVar(
            value=self._parent._cfg.get("sound_alerts", False)
        )
        tk.Checkbutton(
            container, text="Sound alerts", variable=self._sound_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=BG_DARK, activeforeground=ACCENT,
            command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._auto_container_var = tk.BooleanVar(
            value=self._parent._cfg.get("auto_open_containers", False)
        )
        tk.Checkbutton(
            container, text="Auto-open containers", variable=self._auto_container_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=BG_DARK, activeforeground=ACCENT,
            command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        # --- Container Key ---
        self._add_label(container, "Container Key", row)
        self._container_var = tk.StringVar(
            value=self._parent._vk_to_label(self._parent._cfg["container_key"])
            if self._parent._cfg.get("container_key") else "None"
        )
        container_entry = tk.Entry(
            container, textvariable=self._container_var, width=6,
            bg=PANEL_DEEP, fg=TEXT_PRIMARY, font=("Consolas", 10),
            insertbackground=TEXT_PRIMARY, justify="center"
        )
        container_entry.grid(row=row, column=1, sticky="w", pady=2)
        container_entry.bind("<Key>", self._on_container_key)
        row += 1

        # --- Pixel Bar Region ---
        tk.Button(
            container, text="Pixel Bar Region...", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
            font=("Consolas", 9), relief="flat", padx=8, pady=4,
            command=self._on_pixel_bar_region, cursor="hand2"
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        row += 1

        # --- Separator ---
        ttk.Separator(container, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=6
        )
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

    def _on_bite_change(self):
        val = self._bite_var.get()
        self._parent._bite_sensitivity = val
        self._parent._bite_watcher.strike_value = val
        self._parent._amplitude._strike = val
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
        self._parent._cfg["auto_delete_junk"] = self._auto_delete_var.get()
        self._parent._cfg["sound_alerts"] = self._sound_var.get()
        self._parent._cfg["auto_open_containers"] = self._auto_container_var.get()
        if self._parent._bot:
            self._parent._bot.stop_on_player_nearby = self._stop_player_var.get()
            self._parent._bot.stop_on_bags_full = self._stop_bags_var.get()
            self._parent._bot.auto_delete_junk = self._auto_delete_var.get()
            self._parent._bot.auto_open_containers = self._auto_container_var.get()
        self._parent._save_cfg()

    def _on_container_key(self, event):
        vk = self._parent._keysym_to_vk(event.keysym)
        if vk:
            self._parent._cfg["container_key"] = vk
            self._container_var.set(self._parent._vk_to_label(vk))
            if self._parent._bot:
                self._parent._bot.container_key = vk
            self._parent._save_cfg()

    def _on_pixel_bar_region(self):
        """Open dialog to set/clear the pixel bar scan region."""
        dlg = tk.Toplevel(self)
        dlg.title("Pixel Bar Region")
        dlg.configure(bg=BG_DARK)
        dlg.geometry("260x200")
        dlg.transient(self)
        dlg.grab_set()

        cur = self._parent._cfg.get("pixel_bar_region")
        cached = self._parent._pixel_bridge.get_bar_position()
        defaults = cur or cached or {"left": 0, "top": 0, "width": 200, "height": 20}

        fields = {}
        for i, key in enumerate(["left", "top", "width", "height"]):
            tk.Label(dlg, text=key.capitalize(), bg=BG_DARK, fg=TEXT_DIM,
                     font=("Consolas", 9)).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            var = tk.IntVar(value=defaults.get(key, 0))
            tk.Entry(dlg, textvariable=var, width=8, bg=PANEL_DEEP, fg=TEXT_PRIMARY,
                     font=("Consolas", 10), insertbackground=TEXT_PRIMARY
                     ).grid(row=i, column=1, padx=8, pady=4)
            fields[key] = var

        def _apply():
            region = {k: v.get() for k, v in fields.items()}
            self._parent._cfg["pixel_bar_region"] = region
            self._parent._pixel_bridge.set_scan_region(region)
            self._parent._save_cfg()
            dlg.destroy()

        def _auto():
            self._parent._cfg["pixel_bar_region"] = None
            self._parent._pixel_bridge.set_scan_region(None)
            self._parent._save_cfg()
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=BG_DARK)
        btn_row.grid(row=4, column=0, columnspan=2, pady=12)
        tk.Button(btn_row, text="Apply", bg=ACCENT, fg="black",
                  font=("Consolas", 9), relief="flat", padx=8, pady=4,
                  command=_apply).pack(side="left", padx=4)
        tk.Button(btn_row, text="Auto-detect", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
                  font=("Consolas", 9), relief="flat", padx=8, pady=4,
                  command=_auto).pack(side="left", padx=4)

    def _on_topmost(self):
        val = self._topmost_var.get()
        self._parent._cfg["always_on_top"] = val
        self._parent.attributes("-topmost", val)
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
        self._parent._bite_sensitivity = DEFAULT_CONFIG["bite_sensitivity"]
        self._parent._bite_watcher.strike_value = DEFAULT_CONFIG["bite_sensitivity"]
        self._parent._amplitude._strike = DEFAULT_CONFIG["bite_sensitivity"]
        self._parent.attributes("-topmost", DEFAULT_CONFIG["always_on_top"])
        if self._parent._bot:
            self._parent._bot.set_cast_key(DEFAULT_CONFIG["cast_key"])
            self._parent._bot.set_lure_key(DEFAULT_CONFIG["lure_key"])
            self._parent._bot.loot_wait_min = DEFAULT_CONFIG["loot_wait_min"]
            self._parent._bot.loot_wait_max = DEFAULT_CONFIG["loot_wait_max"]
            self._parent._bot.stop_on_player_nearby = DEFAULT_CONFIG["stop_on_player"]
            self._parent._bot.stop_on_bags_full = DEFAULT_CONFIG["stop_on_bags"]
            self._parent._bot.auto_calibrate = DEFAULT_CONFIG["auto_calibrate"]
            self._parent._bot.auto_delete_junk = DEFAULT_CONFIG["auto_delete_junk"]
            self._parent._bot.container_key = DEFAULT_CONFIG["container_key"]
            self._parent._bot.auto_open_containers = DEFAULT_CONFIG["auto_open_containers"]
        self._parent._pixel_bridge.set_scan_region(DEFAULT_CONFIG["pixel_bar_region"])
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
        w = self._cfg.get("window_width", 200)
        h = self._cfg.get("window_height", 500)
        self.geometry(f"{w}x{h}")
        self.minsize(160, 300)

        # Always on top
        if self._cfg.get("always_on_top", True):
            self.attributes("-topmost", True)

        # Core components
        self._pc = PixelClassifier()
        self._pc.colour_multiplier = self._cfg["colour_multiplier"]
        self._pc.colour_closeness_multiplier = self._cfg["colour_closeness_multiplier"]
        self._pc.mode = ClassifierMode.Red if self._cfg["colour_mode"] == "Red" else ClassifierMode.Blue
        self._pc.set_configuration(wow_process.is_wow_classic())
        self._bobber_finder = SearchBobberFinder(self._pc)
        self._bite_sensitivity = self._cfg.get("bite_sensitivity", STRIKE_VALUE)
        self._bite_watcher = PositionBiteWatcher(self._bite_sensitivity)
        self._bot: Optional[LaksefiskBot] = None
        self._bot_thread: Optional[threading.Thread] = None
        self._cast_key = self._cfg["cast_key"]
        self._lure_key: Optional[int] = self._cfg["lure_key"]
        self._loot_min = self._cfg["loot_wait_min"]
        self._loot_max = self._cfg["loot_wait_max"]

        self._log_queue: queue.Queue = queue.Queue()
        self._screenshot_photo: Optional[ImageTk.PhotoImage] = None
        self._last_ss_time: float = 0.0
        self._is_running = False

        # Fish tracker (pixel bridge mode)
        self._fish_tracker = FishTracker(loot_file=LOOT_FILE)
        self._fish_tracker.load_loot()
        self._fish_tracker.set_on_update(lambda: self.after(0, self._update_fish_display))

        # Pixel bridge (replaces OCR for loot detection)
        scan_region = self._cfg.get("pixel_bar_region")
        self._pixel_bridge = PixelBridge(scan_region=scan_region)

        # Sound alert state tracking
        self._prev_player_nearby = False
        self._prev_bags_full = False
        self._prev_whisper_flag = 0

        self._bobber_finder.bitmap_callbacks.append(self._on_bitmap_event)

        self._build_ui()
        self._setup_logging()
        self._poll()
        self._check_addon_status()


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
        self._paned = ttk.PanedWindow(self._main_frame, orient="vertical")
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

        # Save config on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_status_bar(self):
        bar = tk.Frame(self._main_frame, bg=BG_DARK, pady=4, padx=4)
        bar.pack(fill="x")

        # Play/stop toggle — canvas-drawn circle
        self._toggle_canvas = tk.Canvas(
            bar, width=32, height=32, bg=BG_DARK,
            highlightthickness=0, cursor="hand2"
        )
        self._toggle_canvas.pack(side="left", padx=(0, 6))
        self._toggle_canvas.bind("<Button-1>", self._on_toggle)
        self._draw_toggle()

        # Status text
        self._status_var = tk.StringVar(value="Idle")
        self._status_label = tk.Label(
            bar, textvariable=self._status_var, bg=BG_DARK,
            fg=ACCENT, font=("Consolas", 12, "bold")
        )
        self._status_label.pack(side="left", padx=(0, 8))

        # Addon status — dot + label
        self._addon_canvas = tk.Canvas(
            bar, width=14, height=14, bg=BG_DARK, highlightthickness=0
        )
        self._addon_canvas.pack(side="left", padx=(0, 2))
        self._addon_dot = self._addon_canvas.create_oval(1, 1, 13, 13, fill=TEXT_DIM)
        self._addon_label = tk.Label(
            bar, text="No addon", bg=BG_DARK,
            fg=TEXT_DIM, font=("Consolas", 8)
        )
        self._addon_label.pack(side="left", padx=(0, 4))

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
            self._toggle_canvas.create_oval(2, 2, 30, 30, fill=ALERT, outline="")
            self._toggle_canvas.create_rectangle(10, 10, 22, 22, fill=BG_DARK, outline="")
        else:
            self._toggle_canvas.create_oval(2, 2, 30, 30, fill=ACCENT, outline="")
            self._toggle_canvas.create_polygon(
                13, 8, 13, 24, 25, 16, fill=BG_DARK, outline=""
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
        self._amplitude = AmplitudeOverlay(self._screenshot_canvas, self._bite_sensitivity)

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
            fg=ACCENT, font=("Consolas", 9, "bold"), anchor="w",
            cursor="hand2"
        )
        self._fish_header_label.pack(side="left")
        self._fish_header_label.bind("<Button-1>", lambda _: webbrowser.open(
            os.path.join(_SCRIPT_DIR, "loot.html")))
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
        # Log header sits outside the PanedWindow so it's always visible
        self._log_header = tk.Frame(self, bg=PANEL_BG, pady=2, padx=4)
        self._log_header.pack(fill="x", side="bottom")
        tk.Label(
            self._log_header, text="Log", bg=PANEL_BG, fg=TEXT_DIM,
            font=("Consolas", 9)
        ).pack(side="left")
        self._log_chevron = tk.Label(
            self._log_header, text="\u25b2" if self._cfg.get("log_collapsed", False) else "\u25bc",
            bg=PANEL_BG, fg=TEXT_DIM, font=("Consolas", 8), cursor="hand2"
        )
        self._log_chevron.pack(side="right")
        self._log_chevron.bind("<Button-1>", self._toggle_log)

        # Log content frame goes inside PanedWindow
        self._log_frame = tk.Frame(self._paned, bg=PANEL_BG)

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
        now = time.perf_counter()
        if now - self._last_ss_time < 0.1:  # ~10 fps cap
            return
        self._last_ss_time = now

        bmp = event.bitmap
        point = event.point

        # Crop in bot thread — copy only the small zoomed region, not the full bitmap
        if point != (0, 0):
            iw, ih = bmp.size
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
            img = bmp.crop((x1, y1, x2, y2))
            reticle_pt = (cx - x1, cy - y1)
        else:
            img = bmp.copy()
            reticle_pt = point

        self.after(0, lambda: self._update_screenshot(img, reticle_pt))

    def _update_screenshot(self, img: Image.Image, reticle_pt: Tuple[int, int]):
        draw_reticle(img, reticle_pt)

        cw = self._screenshot_canvas.winfo_width() or 500
        ch = self._screenshot_canvas.winfo_height() or 200
        if cw < 10 or ch < 10:
            return

        iw, ih = img.size
        scale = min(cw / iw, ch / ih)
        new_w = max(1, int(iw * scale))
        new_h = max(1, int(ih * scale))
        img = img.resize((new_w, new_h), Image.NEAREST)
        self._screenshot_photo = ImageTk.PhotoImage(img)
        self._screenshot_canvas.coords(self._ss_img_id, cw // 2, ch // 2)
        self._screenshot_canvas.itemconfig(self._ss_img_id, image=self._screenshot_photo)

        # Redraw amplitude overlay on top
        self._amplitude.draw()

    # ------------------------------------------------------------------
    # Dock detection and layout switching
    # ------------------------------------------------------------------

    def _save_sash_positions(self):
        try:
            n = len(self._paned.panes()) - 1
            positions = [self._paned.sashpos(i) for i in range(n)]
            self._cfg["sash_positions"] = positions
        except Exception:
            pass

    def _restore_sash_positions(self):
        positions = self._cfg.get("sash_positions")
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
        self._bot.auto_delete_junk = self._cfg.get("auto_delete_junk", False)
        self._bot.container_key = self._cfg.get("container_key")
        self._bot.auto_open_containers = self._cfg.get("auto_open_containers", False)
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

    def _play_alert(self, alert_type: str):
        """Play a sound alert in a background thread."""
        if not self._cfg.get("sound_alerts", False):
            return
        def _beep():
            if alert_type == "player":
                for _ in range(3):
                    winsound.Beep(1200, 300)
            elif alert_type == "bags":
                winsound.Beep(800, 500)
            elif alert_type == "stopped":
                winsound.Beep(400, 800)
            elif alert_type == "whisper":
                for _ in range(2):
                    winsound.Beep(1000, 150)
        threading.Thread(target=_beep, daemon=True).start()

    def _check_addon_status(self):
        try:
            data = self._pixel_bridge.read()
            connected = data is not None
        except Exception:
            data = None
            connected = False

        colour = ACCENT if connected else TEXT_DIM
        self._addon_canvas.itemconfig(self._addon_dot, fill=colour)
        self._addon_label.config(
            text="Addon found" if connected else "No addon",
            fg=ACCENT if connected else TEXT_DIM
        )

        # Sound alerts on state changes
        if data is not None:
            if data.player_nearby and not self._prev_player_nearby:
                self._play_alert("player")
            if data.bags_full and not self._prev_bags_full:
                self._play_alert("bags")
            if data.whisper_flag != self._prev_whisper_flag and data.whisper_flag:
                self._play_alert("whisper")
            self._prev_player_nearby = data.player_nearby
            self._prev_bags_full = data.bags_full
            self._prev_whisper_flag = data.whisper_flag

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
        self._cfg["bite_sensitivity"] = self._bite_sensitivity
        self._cfg["log_collapsed"] = self._log_collapsed
        self._cfg["always_on_top"] = bool(self.attributes("-topmost"))
        self._cfg["sound_alerts"] = self._cfg.get("sound_alerts", False)
        self._cfg["pixel_bar_region"] = self._cfg.get("pixel_bar_region")
        self._cfg["container_key"] = self._cfg.get("container_key")
        self._cfg["auto_open_containers"] = self._cfg.get("auto_open_containers", False)
        if self._bot:
            self._cfg["stop_on_player"] = self._bot.stop_on_player_nearby
            self._cfg["stop_on_bags"] = self._bot.stop_on_bags_full
            self._cfg["auto_calibrate"] = self._bot.auto_calibrate
            self._cfg["auto_delete_junk"] = self._bot.auto_delete_junk
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
