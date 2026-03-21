"""
Laksefisk settings popup — unified dark-themed settings dialog.
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from PIL import Image, ImageTk

from constants import (
    ACCENT,
    ALERT,
    BG_DARK,
    DEFAULT_CONFIG,
    PANEL_BG,
    PANEL_DEEP,
    TEXT_DIM,
    TEXT_PRIMARY,
)
from pixel_classifier import ClassifierMode
from widgets import (
    RangeSliderWithEntries,
    SliderWithEntry,
    _bind_hover,
)
if TYPE_CHECKING:
    from gui import App


class SettingsPopup(tk.Toplevel):
    """Unified settings popup — dark themed."""

    def __init__(self, parent: "App", on_change: callable):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("Settings")
        self.configure(bg=BG_DARK)
        self.geometry("420x820")
        self.resizable(True, True)
        self._parent = parent
        self._on_change = on_change
        # Keep both windows on top so they don't disappear behind WoW
        if self._parent._cfg.get("always_on_top", True):
            self.attributes("-topmost", True)
        self.focus_force()
        self.lift()
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

        # ── Keys ──
        row = self._add_section(container, "Keys", row)

        self._add_label(container, "Cast Key", row)
        self._cast_var = tk.StringVar(value=self._parent._vk_to_label(self._parent._cast_key))
        e = tk.Entry(
            container, textvariable=self._cast_var, bg=PANEL_BG,
            fg=TEXT_PRIMARY, font=("Consolas", 10), insertbackground=TEXT_PRIMARY,
            relief="flat", width=8
        )
        e.grid(row=row, column=1, sticky="ew", pady=3, padx=(4, 0))
        e.bind("<FocusIn>", lambda _: self._cast_var.set(""))
        e.bind("<FocusOut>", lambda _: self._cast_var.set(
            self._parent._vk_to_label(self._parent._cast_key)))
        e.bind("<KeyRelease>", self._on_cast_key)
        row += 1

        self._add_label(container, "Lure Key", row)
        lure = self._parent._lure_key
        self._lure_var = tk.StringVar(
            value=self._parent._vk_to_label(lure) if lure else "-")
        e = tk.Entry(
            container, textvariable=self._lure_var, bg=PANEL_BG,
            fg=TEXT_PRIMARY, font=("Consolas", 10), insertbackground=TEXT_PRIMARY,
            relief="flat", width=8
        )
        e.grid(row=row, column=1, sticky="ew", pady=3, padx=(4, 0))
        e.bind("<FocusIn>", lambda _: self._lure_var.set(""))
        e.bind("<FocusOut>", lambda _: self._lure_var.set(
            self._parent._vk_to_label(self._parent._lure_key) if self._parent._lure_key else "-"))
        e.bind("<KeyRelease>", self._on_lure_key)
        row += 1

        # ── Timing ──
        row = self._add_section(container, "Timing", row)

        self._add_label(container, "Loot Wait (s)", row)
        self._loot_range = RangeSliderWithEntries(
            container, from_=0.0, to=10.0, resolution=0.1,
            low=self._parent._loot_min, high=self._parent._loot_max,
            command=self._on_loot_range_change
        )
        self._loot_range.grid(row=row, column=1, sticky="ew", pady=3, padx=(4, 0))
        row += 1

        self._add_label(container, "Bite Sensitivity", row)
        self._bite_slider = SliderWithEntry(
            container, from_=1, to=20, resolution=1,
            value=self._parent._bite_sensitivity,
            command=lambda v: self._on_bite_change(v)
        )
        self._bite_slider.grid(row=row, column=1, sticky="ew", pady=3, padx=(4, 0))
        row += 1

        # ── Detection ──
        row = self._add_section(container, "Detection", row)

        self._add_label(container, "Colour Mode", row)
        mode_frame = tk.Frame(container, bg=BG_DARK)
        mode_frame.grid(row=row, column=1, sticky="w", pady=3, padx=(4, 0))
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

        self._add_label(container, "Colour Multiplier", row)
        self._mult_slider = SliderWithEntry(
            container, from_=0.0, to=3.0, resolution=0.05,
            value=self._parent._pc.colour_multiplier,
            command=lambda v: self._on_mult_change(v)
        )
        self._mult_slider.grid(row=row, column=1, sticky="ew", pady=3, padx=(4, 0))
        row += 1

        self._add_label(container, "Colour Closeness", row)
        self._close_slider = SliderWithEntry(
            container, from_=0.0, to=5.0, resolution=0.1,
            value=self._parent._pc.colour_closeness_multiplier,
            command=lambda v: self._on_close_change(v)
        )
        self._close_slider.grid(row=row, column=1, sticky="ew", pady=3, padx=(4, 0))
        row += 1

        # ── Features ──
        row = self._add_section(container, "Features", row)

        self._auto_cal_var = tk.BooleanVar(
            value=self._parent._cfg.get("auto_calibrate", False)
        )
        tk.Checkbutton(
            container, text="Auto-calibrate on start", variable=self._auto_cal_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_auto_cal
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._stop_friendly_var = tk.BooleanVar(
            value=self._parent._cfg.get("stop_on_friendly", False)
        )
        tk.Checkbutton(
            container, text="Stop on friendly player", variable=self._stop_friendly_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._stop_enemy_var = tk.BooleanVar(
            value=self._parent._cfg.get("stop_on_enemy", False)
        )
        tk.Checkbutton(
            container, text="Stop on enemy player", variable=self._stop_enemy_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._stop_bags_var = tk.BooleanVar(
            value=self._parent._cfg.get("stop_on_bags", False)
        )
        tk.Checkbutton(
            container, text="Stop on bags full", variable=self._stop_bags_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._auto_delete_var = tk.BooleanVar(
            value=self._parent._cfg.get("auto_delete_junk", False)
        )
        tk.Checkbutton(
            container, text="Auto-delete junk", variable=self._auto_delete_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._topmost_var = tk.BooleanVar(
            value=self._parent._cfg.get("always_on_top", True)
        )
        tk.Checkbutton(
            container, text="Always on top", variable=self._topmost_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_topmost
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._sound_var = tk.BooleanVar(
            value=self._parent._cfg.get("sound_alerts", False)
        )
        tk.Checkbutton(
            container, text="Sound alerts", variable=self._sound_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        self._debug_ss_var = tk.BooleanVar(
            value=self._parent._cfg.get("debug_screenshots", False)
        )
        tk.Checkbutton(
            container, text="Debug screenshots", variable=self._debug_ss_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP, activeforeground=ACCENT,
            padx=4, command=self._on_stop_conditions
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        row += 1

        # ── Advanced ──
        row = self._add_section(container, "Advanced", row)

        btn = tk.Button(
            container, text="Pixel Bar Region...", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
            font=("Consolas", 9), relief="flat", padx=8, pady=4,
            command=self._on_pixel_bar_region, cursor="hand2"
        )
        btn.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
        _bind_hover(btn, PANEL_DEEP, ACCENT, TEXT_PRIMARY, "black")
        row += 1

        # Reset
        reset_btn = tk.Button(
            container, text="Reset to Defaults", bg=ALERT, fg="white",
            font=("Consolas", 9), relief="flat", padx=8, pady=4,
            command=self._on_reset, cursor="hand2"
        )
        reset_btn.grid(row=row, column=0, columnspan=2, sticky="w", pady=(12, 0))
        _bind_hover(reset_btn, ALERT, "#ff6680")
        row += 1

        # --- Expandable: Colour Preview ---
        self._preview_expanded = False
        self._preview_btn = tk.Button(
            container, text="\u25b6 Colour Preview", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 9), relief="flat", anchor="w",
            command=self._toggle_preview, cursor="hand2"
        )
        self._preview_btn.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
        row += 1

        self._preview_frame = tk.Frame(container, bg=BG_DARK)
        self._preview_row = row

        btn_row = tk.Frame(self._preview_frame, bg=BG_DARK)
        btn_row.pack(fill="x", pady=4)
        cap_btn = tk.Button(
            btn_row, text="Capture", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
            font=("Consolas", 8), relief="flat", padx=6,
            command=self._on_capture
        )
        cap_btn.pack(side="left", padx=(0, 4))
        _bind_hover(cap_btn, PANEL_DEEP, ACCENT, TEXT_PRIMARY, "black")
        self._live_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            btn_row, text="Live", variable=self._live_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP,
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

    def _add_section(self, parent, text, row):
        """Draw a section header with accent left border."""
        frame = tk.Frame(parent, bg=BG_DARK)
        frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 2))
        tk.Frame(frame, bg=ACCENT, width=3).pack(side="left", fill="y", padx=(0, 6))
        tk.Label(frame, text=text, bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=("Consolas", 9, "bold")).pack(side="left")
        return row + 1

    def _add_label(self, parent, text, row):
        tk.Label(
            parent, text=text, bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 9), anchor="w"
        ).grid(row=row, column=0, sticky="w", pady=3, padx=8)

    def _toggle_preview(self):
        self._preview_expanded = not self._preview_expanded
        if self._preview_expanded:
            self._preview_btn.config(text="\u25bc Colour Preview")
            self._preview_frame.grid(
                row=self._preview_row, column=0, columnspan=2,
                sticky="nsew", pady=4
            )
            self.update_idletasks()
            self.geometry(f"420x{max(820, self.winfo_reqheight())}")
        else:
            self._preview_btn.config(text="\u25b6 Colour Preview")
            self._preview_frame.grid_forget()
            self.geometry("420x820")
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
            img = self._parent._wow_screen.get_bitmap()
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

    def _on_loot_range_change(self, low, high):
        self._parent._loot_min = low
        self._parent._loot_max = high
        if self._parent._bot:
            self._parent._bot.loot_wait_min = low
            self._parent._bot.loot_wait_max = high
        self._parent._save_cfg()

    def _on_bite_change(self, val=None):
        if val is None:
            return
        val = int(val)
        self._parent._bite_sensitivity = val
        self._parent._bite_watcher.strike_value = val
        self._parent._amplitude._strike = val
        self._parent._save_cfg()

    def _on_mode_change(self):
        mode = ClassifierMode.Red if self._mode_var.get() == "Red" else ClassifierMode.Blue
        self._parent._pc.mode = mode
        self._parent._save_cfg()
        self._on_change()

    def _on_mult_change(self, val=None):
        if val is not None:
            self._parent._pc.colour_multiplier = float(val)
        self._parent._save_cfg()
        self._on_change()

    def _on_close_change(self, val=None):
        if val is not None:
            self._parent._pc.colour_closeness_multiplier = float(val)
        self._parent._save_cfg()
        self._on_change()

    def _on_auto_cal(self):
        self._parent._cfg["auto_calibrate"] = self._auto_cal_var.get()
        if self._parent._bot:
            self._parent._bot.auto_calibrate = self._auto_cal_var.get()
        self._parent._save_cfg()

    def _on_stop_conditions(self):
        self._parent._cfg["stop_on_friendly"] = self._stop_friendly_var.get()
        self._parent._cfg["stop_on_enemy"] = self._stop_enemy_var.get()
        self._parent._cfg["stop_on_bags"] = self._stop_bags_var.get()
        self._parent._cfg["auto_delete_junk"] = self._auto_delete_var.get()
        self._parent._cfg["sound_alerts"] = self._sound_var.get()
        self._parent._cfg["debug_screenshots"] = self._debug_ss_var.get()
        if self._parent._bot:
            self._parent._bot.stop_on_friendly_nearby = self._stop_friendly_var.get()
            self._parent._bot.stop_on_enemy_nearby = self._stop_enemy_var.get()
            self._parent._bot.stop_on_bags_full = self._stop_bags_var.get()
            self._parent._bot.auto_delete_junk = self._auto_delete_var.get()
            self._parent._bot.debug_screenshots = self._debug_ss_var.get()
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
        # Don't apply topmost while settings is open — it would cover this dialog.
        # It will be applied in _on_close when settings is dismissed.
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
            self._parent._bot.stop_on_friendly_nearby = DEFAULT_CONFIG["stop_on_friendly"]
            self._parent._bot.stop_on_enemy_nearby = DEFAULT_CONFIG["stop_on_enemy"]
            self._parent._bot.stop_on_bags_full = DEFAULT_CONFIG["stop_on_bags"]
            self._parent._bot.auto_calibrate = DEFAULT_CONFIG["auto_calibrate"]
            self._parent._bot.auto_delete_junk = DEFAULT_CONFIG["auto_delete_junk"]
        self._parent._pixel_bridge.set_scan_region(DEFAULT_CONFIG["pixel_bar_region"])
        self._parent._save_cfg()
        self.destroy()
        self._parent._on_settings()
