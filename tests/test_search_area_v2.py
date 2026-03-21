"""
Test script: Preview the bobber search area with colour tuning.

- Green overlay on the WoW screen showing exactly where the bot searches.
- Small control panel (top-left, above the search area) with:
  - Live preview of captured area with matched pixels highlighted
  - Red/Blue mode toggle
  - Multiplier & Closeness sliders
  - Pixel match count

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


class SearchAreaPreview(tk.Tk):
    def __init__(self):
        super().__init__()

        self._pc = PixelClassifier()
        self._preview_photo = None
        self._live = False
        self._live_id = None
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

        # --- Green overlay showing search boundary on screen ---
        self._overlay = tk.Toplevel(self)
        self._overlay.overrideredirect(True)
        self._overlay.attributes("-topmost", True)
        self._overlay.attributes("-alpha", 0.25)
        self._overlay.configure(bg="#00ff00")
        r = self._region
        # Border thickness
        self._border = 4
        self._overlay.geometry(
            f"{r['width'] + self._border * 2}x{r['height'] + self._border * 2}"
            f"+{r['left'] - self._border}+{r['top'] - self._border}"
        )
        # Cut out the inside so only the border is visible
        inner = tk.Frame(self._overlay, bg="", highlightthickness=0)
        inner.place(x=self._border, y=self._border,
                    width=r["width"], height=r["height"])
        # Make the inner frame transparent by using a label trick
        self._overlay.wm_attributes("-transparentcolor", "#010101")
        inner.configure(bg="#010101")

        # --- Control panel (top-left corner, above search area) ---
        self.title("Colour Explorer")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        # Position: top-left, above the search area
        panel_w = 420
        panel_h = 480
        self.geometry(f"{panel_w}x{panel_h}+10+10")

        self._build_ui()
        self._do_capture()

    def _build_ui(self):
        # Controls frame
        ctrl = ttk.Frame(self)
        ctrl.pack(fill="x", padx=5, pady=5)

        ttk.Button(ctrl, text="Capture", command=self._do_capture).pack(side="left", padx=3)
        self._live_btn = ttk.Button(ctrl, text="Live", command=self._toggle_live)
        self._live_btn.pack(side="left", padx=3)

        self._stats_label = ttk.Label(ctrl, text="Matches: 0", font=("Consolas", 9))
        self._stats_label.pack(side="right", padx=5)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=5)

        # Settings frame
        settings = ttk.Frame(self)
        settings.pack(fill="x", padx=5, pady=5)

        # Row 1: Colour mode
        row1 = ttk.Frame(settings)
        row1.pack(fill="x", pady=2)
        ttk.Label(row1, text="Feather colour:").pack(side="left")
        self._mode_var = tk.StringVar(value="Red")
        ttk.Radiobutton(row1, text="Red", variable=self._mode_var,
                        value="Red", command=self._on_settings_change).pack(side="left", padx=5)
        ttk.Radiobutton(row1, text="Blue", variable=self._mode_var,
                        value="Blue", command=self._on_settings_change).pack(side="left")

        # Row 2: Colour multiplier
        row2 = ttk.Frame(settings)
        row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Multiplier:", width=12).pack(side="left")
        self._mult_var = tk.DoubleVar(value=0.5)
        ttk.Scale(row2, from_=0.1, to=2.0, variable=self._mult_var,
                  orient="horizontal", length=200,
                  command=lambda _: self._on_settings_change()).pack(side="left", fill="x", expand=True)
        self._mult_label = ttk.Label(row2, text="0.50", width=5, font=("Consolas", 9))
        self._mult_label.pack(side="left")

        # Row 3: Closeness multiplier
        row3 = ttk.Frame(settings)
        row3.pack(fill="x", pady=2)
        ttk.Label(row3, text="Closeness:", width=12).pack(side="left")
        self._close_var = tk.DoubleVar(value=2.0)
        ttk.Scale(row3, from_=0.5, to=4.0, variable=self._close_var,
                  orient="horizontal", length=200,
                  command=lambda _: self._on_settings_change()).pack(side="left", fill="x", expand=True)
        self._close_label = ttk.Label(row3, text="2.00", width=5, font=("Consolas", 9))
        self._close_label.pack(side="left")

        # Explanation
        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=5)
        explain = ttk.Label(self, text=(
            "Multiplier: how dominant the feather colour must be vs others.\n"
            "  Lower = stricter (only very red/blue pixels match).\n"
            "Closeness: how similar the other two channels must be.\n"
            "  Higher = more lenient (allows more variation).\n"
            "Green dots = matched pixels. Adjust until only the\n"
            "bobber feather lights up."
        ), font=("Segoe UI", 8), justify="left")
        explain.pack(fill="x", padx=8, pady=4)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=5)

        # Preview image
        self._preview_label = ttk.Label(self)
        self._preview_label.pack(fill="both", expand=True, padx=5, pady=5)

    def _on_settings_change(self):
        mode = self._mode_var.get()
        self._pc.mode = ClassifierMode.Red if mode == "Red" else ClassifierMode.Blue
        self._pc.colour_multiplier = self._mult_var.get()
        self._pc.colour_closeness_multiplier = self._close_var.get()
        self._mult_label.config(text=f"{self._mult_var.get():.2f}")
        self._close_label.config(text=f"{self._close_var.get():.2f}")
        if not self._live:
            self._do_capture()

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
        # Hide overlay briefly so it doesn't appear in capture
        self._overlay.attributes("-alpha", 0)
        self._overlay.update_idletasks()

        bmp = self._ws.get_bitmap()

        self._overlay.attributes("-alpha", 0.25)

        w, h = bmp.size

        # Find matching pixels
        pixels = bmp.load()
        match_points: List[Tuple[int, int]] = []
        for x in range(w):
            for y in range(h):
                r, g, b = pixels[x, y][:3]
                if self._pc.is_match(r, g, b):
                    match_points.append((x, y))

        self._stats_label.config(text=f"Matches: {len(match_points)}")

        # Scale to fit panel width
        panel_w = max(self.winfo_width() - 20, 200)
        ratio = panel_w / w
        preview_w = int(w * ratio)
        preview_h = int(h * ratio)
        preview = bmp.resize((preview_w, preview_h), Image.LANCZOS)
        bmp.close()

        # Draw matched pixels as green dots
        if match_points:
            draw = ImageDraw.Draw(preview)
            for x, y in match_points:
                sx = int(x * ratio)
                sy = int(y * ratio)
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
