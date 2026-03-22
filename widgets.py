"""
Laksefisk widgets — reticle drawer, overlays, dark-themed sliders, tooltips.
"""

from __future__ import annotations

import random
import time
import tkinter as tk
from collections import deque
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from constants import (
    ACCENT,
    ALERT,
    BG_DARK,
    PANEL_BG,
    PANEL_DEEP,
    TEXT_DIM,
    TEXT_PRIMARY,
)


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
        latest_val = None

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
            if latest_val is None or elapsed < 1.0:
                latest_val = v

        # Strike line
        strike_norm = (-self._strike - y_min) / y_range
        strike_y = overlay_top + overlay_h - int(strike_norm * overlay_h)
        if overlay_top <= strike_y <= h:
            line_id = self._canvas.create_line(
                0, strike_y, w, strike_y,
                fill=ALERT, dash=(4, 4)
            )
            self._item_ids.append(line_id)

        # Current value label (top-right of overlay)
        if latest_val is not None:
            val_id = self._canvas.create_text(
                w - 4, overlay_top + 2, text=str(latest_val),
                fill=TEXT_DIM, font=("Consolas", 8), anchor="ne"
            )
            self._item_ids.append(val_id)


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
        tk.Label(tw, text=self.text, justify="left",
                 bg=PANEL_DEEP, fg=TEXT_PRIMARY,
                 relief="flat", bd=0, font=("Segoe UI", 8),
                 padx=6, pady=4, wraplength=300).pack()
        tw.config(highlightbackground=ACCENT, highlightthickness=1)

    def _hide(self, _e):
        if self._tw:
            self._tw.destroy()
            self._tw = None


# ---------------------------------------------------------------------------
# Dark-themed custom widgets
# ---------------------------------------------------------------------------

class DarkSlider(tk.Canvas):
    """Canvas-drawn slider matching dark theme."""

    def __init__(self, parent, from_=0.0, to=1.0, resolution=0.01,
                 value=None, variable=None, command=None, **kw):
        kw.setdefault("height", 24)
        kw.setdefault("bg", BG_DARK)
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._from = float(from_)
        self._to = float(to)
        self._res = float(resolution)
        self._variable = variable
        self._command = command
        self._handle_r = 7
        self._track_h = 4
        self._dragging = False
        self._hover = False

        if value is not None:
            self._val = float(value)
        elif variable is not None:
            self._val = float(variable.get())
        else:
            self._val = self._from

        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        if self._variable:
            self._variable.trace_add("write", self._on_var_change)

    def get(self):
        return self._val

    def set(self, value):
        self._val = self._clamp(float(value))
        if self._variable:
            self._variable.set(self._val)
        self._draw()

    def _clamp(self, v):
        v = max(self._from, min(self._to, v))
        if self._res > 0:
            v = round(round(v / self._res) * self._res, 10)
        return v

    def _val_to_x(self, v):
        w = self.winfo_width()
        pad = self._handle_r + 2
        usable = w - 2 * pad
        if self._to == self._from:
            return pad
        frac = (v - self._from) / (self._to - self._from)
        return pad + frac * usable

    def _x_to_val(self, x):
        w = self.winfo_width()
        pad = self._handle_r + 2
        usable = w - 2 * pad
        if usable <= 0:
            return self._from
        frac = (x - pad) / usable
        frac = max(0.0, min(1.0, frac))
        return self._clamp(self._from + frac * (self._to - self._from))

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10:
            return
        cy = h // 2
        pad = self._handle_r + 2
        th = self._track_h

        # Track background
        self.create_rectangle(pad, cy - th // 2, w - pad, cy + th // 2,
                              fill=PANEL_DEEP, outline="")
        # Filled portion
        hx = self._val_to_x(self._val)
        self.create_rectangle(pad, cy - th // 2, hx, cy + th // 2,
                              fill=ACCENT, outline="")
        # Handle
        fill = "white" if self._dragging else ("#40e0c0" if self._hover else ACCENT)
        self.create_oval(hx - self._handle_r, cy - self._handle_r,
                         hx + self._handle_r, cy + self._handle_r,
                         fill=fill, outline="")

    def _set_from_x(self, x):
        new_val = self._x_to_val(x)
        if new_val != self._val:
            self._val = new_val
            if self._variable:
                self._variable.set(self._val)
            self._draw()
            if self._command:
                self._command(self._val)

    def _on_click(self, e):
        self._dragging = True
        self._set_from_x(e.x)

    def _on_drag(self, e):
        if self._dragging:
            self._set_from_x(e.x)

    def _on_release(self, _e):
        self._dragging = False
        self._draw()

    def _on_enter(self, _e):
        self._hover = True
        self._draw()

    def _on_leave(self, _e):
        self._hover = False
        self._draw()

    def _on_var_change(self, *_args):
        try:
            v = float(self._variable.get())
            if v != self._val:
                self._val = self._clamp(v)
                self._draw()
        except (ValueError, tk.TclError):
            pass


class RangeSlider(tk.Canvas):
    """Dual-handle range slider."""

    def __init__(self, parent, from_=0.0, to=1.0, resolution=0.01,
                 low=None, high=None, command=None, **kw):
        kw.setdefault("height", 24)
        kw.setdefault("bg", BG_DARK)
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._from = float(from_)
        self._to = float(to)
        self._res = float(resolution)
        self._command = command
        self._handle_r = 7
        self._track_h = 4
        self._low = self._clamp(float(low) if low is not None else self._from)
        self._high = self._clamp(float(high) if high is not None else self._to)
        self._drag_handle = None
        self._hover_handle = None

        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)

    def get_low(self):
        return self._low

    def get_high(self):
        return self._high

    def set_low(self, v):
        self._low = self._clamp(float(v))
        if self._low > self._high:
            self._low = self._high
        self._draw()

    def set_high(self, v):
        self._high = self._clamp(float(v))
        if self._high < self._low:
            self._high = self._low
        self._draw()

    def _clamp(self, v):
        v = max(self._from, min(self._to, v))
        if self._res > 0:
            v = round(round(v / self._res) * self._res, 10)
        return v

    def _val_to_x(self, v):
        w = self.winfo_width()
        pad = self._handle_r + 2
        usable = w - 2 * pad
        if self._to == self._from:
            return pad
        frac = (v - self._from) / (self._to - self._from)
        return pad + frac * usable

    def _x_to_val(self, x):
        w = self.winfo_width()
        pad = self._handle_r + 2
        usable = w - 2 * pad
        if usable <= 0:
            return self._from
        frac = (x - pad) / usable
        frac = max(0.0, min(1.0, frac))
        return self._clamp(self._from + frac * (self._to - self._from))

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 10:
            return
        cy = h // 2
        pad = self._handle_r + 2
        th = self._track_h

        self.create_rectangle(pad, cy - th // 2, w - pad, cy + th // 2,
                              fill=PANEL_DEEP, outline="")
        lx = self._val_to_x(self._low)
        hx = self._val_to_x(self._high)
        self.create_rectangle(lx, cy - th // 2, hx, cy + th // 2,
                              fill=ACCENT, outline="")

        for handle, vx in [("low", lx), ("high", hx)]:
            active = self._drag_handle == handle
            hover = self._hover_handle == handle
            fill = "white" if active else ("#40e0c0" if hover else ACCENT)
            self.create_oval(vx - self._handle_r, cy - self._handle_r,
                             vx + self._handle_r, cy + self._handle_r,
                             fill=fill, outline="")

    def _nearest_handle(self, x):
        lx = self._val_to_x(self._low)
        hx = self._val_to_x(self._high)
        return "low" if abs(x - lx) <= abs(x - hx) else "high"

    def _on_click(self, e):
        self._drag_handle = self._nearest_handle(e.x)
        self._update_from_x(e.x)

    def _on_drag(self, e):
        if self._drag_handle:
            self._update_from_x(e.x)

    def _on_release(self, _e):
        self._drag_handle = None
        self._draw()

    def _on_motion(self, e):
        h = self._nearest_handle(e.x)
        if h != self._hover_handle:
            self._hover_handle = h
            self._draw()

    def _on_leave(self, _e):
        self._hover_handle = None
        self._draw()

    def _update_from_x(self, x):
        v = self._x_to_val(x)
        changed = False
        if self._drag_handle == "low":
            v = min(v, self._high)
            if v != self._low:
                self._low = v
                changed = True
        elif self._drag_handle == "high":
            v = max(v, self._low)
            if v != self._high:
                self._high = v
                changed = True
        if changed:
            self._draw()
            if self._command:
                self._command(self._low, self._high)


class SliderWithEntry(tk.Frame):
    """Composite: DarkSlider + Entry field side by side."""

    def __init__(self, parent, from_=0.0, to=1.0, resolution=0.01,
                 value=None, variable=None, command=None, **kw):
        super().__init__(parent, bg=kw.pop("bg", BG_DARK))
        self._from = float(from_)
        self._to = float(to)
        self._res = float(resolution)
        self._command = command
        self._variable = variable

        if value is not None:
            self._val = float(value)
        elif variable is not None:
            self._val = float(variable.get())
        else:
            self._val = self._from

        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=0)

        self._slider = DarkSlider(
            self, from_=from_, to=to, resolution=resolution,
            value=self._val, command=self._on_slider
        )
        self._slider.grid(row=0, column=0, sticky="ew")

        self._entry_var = tk.StringVar(value=self._format(self._val))
        self._entry = tk.Entry(
            self, textvariable=self._entry_var, width=6,
            font=("Consolas", 10), bg=PANEL_BG, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat", justify="center"
        )
        self._entry.grid(row=0, column=1, padx=(4, 0))
        self._entry.bind("<Return>", self._on_entry)
        self._entry.bind("<FocusOut>", self._on_entry)

        if self._variable:
            self._variable.trace_add("write", self._on_var_change)

    def get(self):
        return self._val

    def set(self, value):
        self._val = self._clamp(float(value))
        self._slider.set(self._val)
        self._entry_var.set(self._format(self._val))
        if self._variable:
            self._variable.set(self._val)

    def _clamp(self, v):
        v = max(self._from, min(self._to, v))
        if self._res > 0:
            v = round(round(v / self._res) * self._res, 10)
        return v

    def _format(self, v):
        if self._res >= 1:
            return str(int(v))
        decimals = max(1, len(str(self._res).rstrip("0").split(".")[-1]))
        return f"{v:.{decimals}f}"

    def _on_slider(self, v):
        self._val = v
        self._entry_var.set(self._format(v))
        if self._variable:
            self._variable.set(v)
        if self._command:
            self._command(v)

    def _on_entry(self, _e=None):
        try:
            v = self._clamp(float(self._entry_var.get()))
        except ValueError:
            v = self._val
        self._val = v
        self._slider.set(v)
        self._entry_var.set(self._format(v))
        if self._variable:
            self._variable.set(v)
        if self._command:
            self._command(v)

    def _on_var_change(self, *_args):
        try:
            v = float(self._variable.get())
            if v != self._val:
                self._val = self._clamp(v)
                self._slider.set(self._val)
                self._entry_var.set(self._format(self._val))
        except (ValueError, tk.TclError):
            pass


class RangeSliderWithEntries(tk.Frame):
    """Composite: [Entry_min] [RangeSlider] [Entry_max]."""

    def __init__(self, parent, from_=0.0, to=1.0, resolution=0.01,
                 low=None, high=None, command=None, **kw):
        super().__init__(parent, bg=kw.pop("bg", BG_DARK))
        self._from = float(from_)
        self._to = float(to)
        self._res = float(resolution)
        self._command = command

        low_v = float(low) if low is not None else self._from
        high_v = float(high) if high is not None else self._to

        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.columnconfigure(2, weight=0)

        self._low_var = tk.StringVar(value=self._format(low_v))
        self._low_entry = tk.Entry(
            self, textvariable=self._low_var, width=5,
            font=("Consolas", 10), bg=PANEL_BG, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat", justify="center"
        )
        self._low_entry.grid(row=0, column=0)
        self._low_entry.bind("<Return>", self._on_low_entry)
        self._low_entry.bind("<FocusOut>", self._on_low_entry)

        self._slider = RangeSlider(
            self, from_=from_, to=to, resolution=resolution,
            low=low_v, high=high_v, command=self._on_slider
        )
        self._slider.grid(row=0, column=1, sticky="ew", padx=4)

        self._high_var = tk.StringVar(value=self._format(high_v))
        self._high_entry = tk.Entry(
            self, textvariable=self._high_var, width=5,
            font=("Consolas", 10), bg=PANEL_BG, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat", justify="center"
        )
        self._high_entry.grid(row=0, column=2)
        self._high_entry.bind("<Return>", self._on_high_entry)
        self._high_entry.bind("<FocusOut>", self._on_high_entry)

    def get_low(self):
        return self._slider.get_low()

    def get_high(self):
        return self._slider.get_high()

    def set_low(self, v):
        self._slider.set_low(v)
        self._low_var.set(self._format(self._slider.get_low()))

    def set_high(self, v):
        self._slider.set_high(v)
        self._high_var.set(self._format(self._slider.get_high()))

    def _clamp(self, v):
        v = max(self._from, min(self._to, v))
        if self._res > 0:
            v = round(round(v / self._res) * self._res, 10)
        return v

    def _format(self, v):
        if self._res >= 1:
            return str(int(v))
        decimals = max(1, len(str(self._res).rstrip("0").split(".")[-1]))
        return f"{v:.{decimals}f}"

    def _on_slider(self, low, high):
        self._low_var.set(self._format(low))
        self._high_var.set(self._format(high))
        if self._command:
            self._command(low, high)

    def _on_low_entry(self, _e=None):
        try:
            v = self._clamp(float(self._low_var.get()))
        except ValueError:
            v = self._slider.get_low()
        self._slider.set_low(v)
        self._low_var.set(self._format(self._slider.get_low()))
        if self._command:
            self._command(self._slider.get_low(), self._slider.get_high())

    def _on_high_entry(self, _e=None):
        try:
            v = self._clamp(float(self._high_var.get()))
        except ValueError:
            v = self._slider.get_high()
        self._slider.set_high(v)
        self._high_var.set(self._format(self._slider.get_high()))
        if self._command:
            self._command(self._slider.get_low(), self._slider.get_high())


def _bind_hover(widget, normal_bg, hover_bg, normal_fg=None, hover_fg=None):
    """Utility to add hover color effects to any widget."""
    def _enter(_e):
        widget.configure(bg=hover_bg)
        if hover_fg:
            widget.configure(fg=hover_fg)
    def _leave(_e):
        widget.configure(bg=normal_bg)
        if normal_fg:
            widget.configure(fg=normal_fg)
    widget.bind("<Enter>", _enter)
    widget.bind("<Leave>", _leave)
