"""
Test script: Preview the bobber search area with colour tuning.

- Green overlay on the WoW screen showing exactly where the bot searches.
- Small control panel with:
  - Live preview of captured area with matched pixels highlighted
  - Red/Blue mode toggle
  - Multiplier & Closeness sliders + editable value fields
  - Expandable colour algorithm map (below preview) with white border
    around matched region
  - Overlay on/off toggle
  - Tooltips on hover

Usage:
    python tests/test_search_area.py
"""

import sys
import os
import tkinter as tk
from tkinter import ttk
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageTk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pixel_classifier import ClassifierMode, PixelClassifier
from wow_screen import WowScreen


# ---------------------------------------------------------------------------
# Tooltip
# ---------------------------------------------------------------------------

class Tooltip:
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
# Colour map generator
# ---------------------------------------------------------------------------

def generate_colour_map(pc: PixelClassifier, size: int = 256) -> Image.Image:
    """Full 256x256 colour map.

    For Red mode:  X = green (0..255), Y = blue (255..0 top-to-bottom),
                   red channel fixed at 255.
    For Blue mode: X = green (0..255), Y = red (255..0 top-to-bottom),
                   blue channel fixed at 255.

    Matched pixels shown in actual colour. Non-matched shown dark grey.
    White 1px border drawn around the contiguous matched region.
    """
    img = Image.new("RGB", (size, size))
    match_mask = Image.new("L", (size, size), 0)
    px = img.load()
    mx = match_mask.load()

    for x in range(size):
        for y in range(size):
            ch1 = x          # green
            ch2 = 255 - y    # blue (red mode) or red (blue mode)

            if pc.mode == ClassifierMode.Red:
                r, g, b = 255, ch1, ch2
            else:
                r, g, b = ch2, ch1, 255

            if pc.is_match(r, g, b):
                px[x, y] = (r, g, b)
                mx[x, y] = 255
            else:
                px[x, y] = (30, 30, 30)

    # Draw white border around matched region
    draw = ImageDraw.Draw(img)
    for x in range(size):
        for y in range(size):
            if mx[x, y] == 0:
                continue
            # Check if this pixel is on the edge of the matched region
            is_edge = False
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nx, ny = x + dx, y + dy
                if nx < 0 or nx >= size or ny < 0 or ny >= size or mx[nx, ny] == 0:
                    is_edge = True
                    break
            if is_edge:
                draw.point((x, y), fill="white")

    return img


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

PANEL_W = 440
PANEL_H_COLLAPSED = 480
CMAP_EXTRA_H = 310


class SearchAreaPreview(tk.Tk):
    def __init__(self):
        super().__init__()

        self._pc = PixelClassifier()
        self._preview_photo = None
        self._cmap_photo = None
        self._live = False
        self._live_id = None
        self._cmap_visible = False
        self._overlay_visible = True
        self._ws = WowScreen()

        # Get screen info via tkinter
        self._screen_w = self.winfo_screenwidth()
        self._screen_h = self.winfo_screenheight()

        self._region = {
            "left": self._screen_w // 4,
            "top": self._screen_h // 4,
            "width": self._screen_w // 2,
            "height": self._screen_h // 2 - 100,
        }

        # --- Green border overlay ---
        self._overlay = tk.Toplevel(self)
        self._overlay.overrideredirect(True)
        self._overlay.attributes("-topmost", True)
        self._overlay.attributes("-alpha", 0.25)
        self._overlay.configure(bg="#00ff00")
        r = self._region
        border = 4
        self._overlay.geometry(
            f"{r['width'] + border * 2}x{r['height'] + border * 2}"
            f"+{r['left'] - border}+{r['top'] - border}"
        )
        self._overlay.wm_attributes("-transparentcolor", "#010101")
        inner = tk.Frame(self._overlay, bg="#010101", highlightthickness=0)
        inner.place(x=border, y=border, width=r["width"], height=r["height"])

        # --- Control panel ---
        self.title("Colour Explorer")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self.geometry(f"{PANEL_W}x{PANEL_H_COLLAPSED}+10+10")

        self._build_ui()
        self._do_capture()

    # ── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top buttons
        ctrl = ttk.Frame(self)
        ctrl.pack(fill="x", padx=5, pady=5)

        cap_btn = ttk.Button(ctrl, text="Capture", command=self._do_capture)
        cap_btn.pack(side="left", padx=3)
        Tooltip(cap_btn, "Take a single snapshot of the search area\nand show matched pixels.")

        self._live_btn = ttk.Button(ctrl, text="Live", command=self._toggle_live)
        self._live_btn.pack(side="left", padx=3)
        Tooltip(self._live_btn, "Toggle live updating (captures every 0.5s).\n"
                "Use to see detection in real-time while fishing.")

        self._overlay_btn = ttk.Button(ctrl, text="Overlay: ON",
                                       command=self._toggle_overlay)
        self._overlay_btn.pack(side="left", padx=3)
        Tooltip(self._overlay_btn, "Show/hide the green border on the WoW screen\n"
                "marking the bobber search area.")

        self._stats_label = ttk.Label(ctrl, text="Matches: 0", font=("Consolas", 9))
        self._stats_label.pack(side="right", padx=5)
        Tooltip(self._stats_label, "Matched pixel count.\n"
                "Bobber feather is typically 20-200.\n"
                ">1000 means settings are too loose.")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=5)

        # Settings
        settings = ttk.Frame(self)
        settings.pack(fill="x", padx=5, pady=5)

        # Colour mode
        row1 = ttk.Frame(settings)
        row1.pack(fill="x", pady=2)
        lbl = ttk.Label(row1, text="Feather colour:")
        lbl.pack(side="left")
        Tooltip(lbl, "Red for most bobbers, Blue for special ones.")
        self._mode_var = tk.StringVar(value="Red")
        ttk.Radiobutton(row1, text="Red", variable=self._mode_var,
                         value="Red", command=self._on_settings_change).pack(side="left", padx=5)
        ttk.Radiobutton(row1, text="Blue", variable=self._mode_var,
                         value="Blue", command=self._on_settings_change).pack(side="left")

        # Multiplier
        self._mult_var = self._build_slider_row(
            settings, "Multiplier:", 0.1, 2.0, 0.5,
            "How dominant the feather colour must be vs others.\n"
            "Lower = stricter, Higher = more lenient.\n"
            "Formula: dominant * multiplier > other_channel"
        )

        # Closeness
        self._close_var = self._build_slider_row(
            settings, "Closeness:", 0.5, 4.0, 2.0,
            "How similar the two non-dominant channels must be.\n"
            "Higher = more lenient (bigger difference allowed).\n"
            "Formula: min(ch1,ch2) * closeness > max(ch1,ch2) - 20"
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=5)

        # Preview image
        self._preview_label = ttk.Label(self)
        self._preview_label.pack(fill="both", expand=True, padx=5, pady=5)

        # Colour map toggle (below preview)
        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=5)
        self._cmap_toggle_frame = ttk.Frame(self)
        self._cmap_toggle_frame.pack(fill="x", padx=5)

        self._cmap_toggle_btn = ttk.Button(self._cmap_toggle_frame,
                                           text="\u25b6 Colour Map",
                                           command=self._toggle_cmap)
        self._cmap_toggle_btn.pack(side="left", pady=3)
        Tooltip(self._cmap_toggle_btn, "Show/hide the full colour map.\n"
                "Shows which colours the algorithm matches.\n"
                "White border = edge of matched region.")

        # Colour map panel (hidden)
        self._cmap_panel = ttk.Frame(self)

        cmap_inner = ttk.Frame(self._cmap_panel)
        cmap_inner.pack(padx=5, pady=5)

        self._cmap_ylabel = ttk.Label(cmap_inner, font=("Consolas", 8))
        self._cmap_ylabel.pack(side="left", padx=(0, 3))

        cmap_right = ttk.Frame(cmap_inner)
        cmap_right.pack(side="left")

        self._cmap_label = ttk.Label(cmap_right)
        self._cmap_label.pack()
        Tooltip(self._cmap_label, "Full colour map (256x256).\n"
                "Each pixel = a colour at full red/blue intensity.\n"
                "X = Green channel (0 left, 255 right).\n"
                "Y = Blue/Red channel (255 top, 0 bottom).\n"
                "Bright = matched. Dark grey = rejected.\n"
                "White border = boundary of matched colours.")

        self._cmap_xlabel = ttk.Label(cmap_right, font=("Consolas", 8))
        self._cmap_xlabel.pack()

    def _build_slider_row(self, parent, label_text, min_val, max_val, default, tooltip):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)

        lbl = ttk.Label(row, text=label_text, width=12)
        lbl.pack(side="left")
        Tooltip(lbl, tooltip)

        var = tk.DoubleVar(value=default)
        ttk.Scale(row, from_=min_val, to=max_val, variable=var,
                  orient="horizontal", length=200,
                  command=lambda _: self._on_settings_change()).pack(
            side="left", fill="x", expand=True)

        entry_var = tk.StringVar(value=f"{default:.2f}")
        entry = ttk.Entry(row, textvariable=entry_var, width=6, font=("Consolas", 9))
        entry.pack(side="left", padx=(5, 0))

        var.trace_add("write", lambda *_: entry_var.set(f"{var.get():.2f}"))

        def _commit(_e=None):
            try:
                v = float(entry_var.get())
                var.set(max(min_val, min(max_val, v)))
                self._on_settings_change()
            except ValueError:
                entry_var.set(f"{var.get():.2f}")

        entry.bind("<Return>", _commit)
        entry.bind("<FocusOut>", _commit)

        return var

    # ── Overlay ─────────────────────────────────────────────────────────

    def _toggle_overlay(self):
        self._overlay_visible = not self._overlay_visible
        if self._overlay_visible:
            self._overlay.deiconify()
            self._overlay_btn.config(text="Overlay: ON")
        else:
            self._overlay.withdraw()
            self._overlay_btn.config(text="Overlay: OFF")

    # ── Colour map ──────────────────────────────────────────────────────

    def _toggle_cmap(self):
        self._cmap_visible = not self._cmap_visible
        if self._cmap_visible:
            self._cmap_toggle_btn.config(text="\u25bc Colour Map")
            self._cmap_panel.pack(fill="x", after=self._cmap_toggle_frame)
            self._update_cmap()
            w = self.winfo_width()
            h = self.winfo_height()
            self.geometry(f"{w}x{h + CMAP_EXTRA_H}")
        else:
            self._cmap_toggle_btn.config(text="\u25b6 Colour Map")
            self._cmap_panel.pack_forget()
            w = self.winfo_width()
            h = self.winfo_height()
            self.geometry(f"{w}x{max(PANEL_H_COLLAPSED, h - CMAP_EXTRA_H)}")

    def _update_cmap(self):
        if not self._cmap_visible:
            return

        if self._pc.mode == ClassifierMode.Red:
            self._cmap_ylabel.config(text="Blue\n255\n\n\n\n\n\n\n\n0")
            self._cmap_xlabel.config(text="0 ─── Green ─── 255")
        else:
            self._cmap_ylabel.config(text="Red\n255\n\n\n\n\n\n\n\n0")
            self._cmap_xlabel.config(text="0 ─── Green ─── 255")

        cmap = generate_colour_map(self._pc, size=256)
        self._cmap_photo = ImageTk.PhotoImage(cmap)
        self._cmap_label.config(image=self._cmap_photo)

    # ── Settings ────────────────────────────────────────────────────────

    def _on_settings_change(self):
        mode = self._mode_var.get()
        self._pc.mode = ClassifierMode.Red if mode == "Red" else ClassifierMode.Blue
        self._pc.colour_multiplier = self._mult_var.get()
        self._pc.colour_closeness_multiplier = self._close_var.get()
        if self._cmap_visible:
            self._update_cmap()
        if not self._live:
            self._do_capture()

    # ── Live / Capture ──────────────────────────────────────────────────

    def _toggle_live(self):
        self._live = not self._live
        self._live_btn.config(text="Stop" if self._live else "Live")
        if self._live:
            self._live_update()
        elif self._live_id:
            self.after_cancel(self._live_id)
            self._live_id = None

    def _live_update(self):
        if not self._live:
            return
        self._do_capture()
        self._live_id = self.after(500, self._live_update)

    def _do_capture(self):
        if self._overlay_visible:
            self._overlay.attributes("-alpha", 0)
            self._overlay.update_idletasks()

        bmp = self._ws.get_bitmap()

        if self._overlay_visible:
            self._overlay.attributes("-alpha", 0.25)

        w, h = bmp.size
        pixels = bmp.load()
        match_points: List[Tuple[int, int]] = []
        for x in range(w):
            for y in range(h):
                r, g, b = pixels[x, y][:3]
                if self._pc.is_match(r, g, b):
                    match_points.append((x, y))

        self._stats_label.config(text=f"Matches: {len(match_points)}")

        panel_w = max(self.winfo_width() - 20, 200)
        ratio = panel_w / w
        preview = bmp.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
        bmp.close()

        if match_points:
            draw = ImageDraw.Draw(preview)
            for x, y in match_points:
                sx, sy = int(x * ratio), int(y * ratio)
                draw.rectangle([sx - 1, sy - 1, sx + 1, sy + 1], fill="#00ff00")

        self._preview_photo = ImageTk.PhotoImage(preview)
        self._preview_label.config(image=self._preview_photo)

    def destroy(self):
        if self._live_id:
            self.after_cancel(self._live_id)
        self._overlay.destroy()
        super().destroy()


if __name__ == "__main__":
    app = SearchAreaPreview()
    app.mainloop()
