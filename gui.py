"""
Laksefisk GUI — Dark-themed, resizable fishing bot interface.

Layout: status bar → bobber view + amplitude overlay → fish list → log (vertical stack)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
import winsound
from tkinter import ttk
from typing import Optional, Tuple

from PIL import Image, ImageTk

import wow_process
from bite_watcher import PositionBiteWatcher
from bobber_calibration import sweep_calibrate
from bobber_finder import SearchBobberFinder
from constants import (
    ACCENT,
    ALERT,
    BG_DARK,
    LOOT_FILE,
    PANEL_BG,
    PANEL_DEEP,
    STRIKE_VALUE,
    TEXT_DIM,
    TEXT_PRIMARY,
    _load_config,
    _save_config,
    _SCRIPT_DIR,
)
from fish_tracker import FishTracker
from fishing_bot import LaksefiskBot
from models import BobberBitmapEvent, FishingAction, FishingEvent
from pixel_bridge import PixelBridge
from pixel_classifier import ClassifierMode, PixelClassifier
from settings import SettingsPopup
from widgets import (
    AmplitudeOverlay,
    FlyingFishOverlay,
    _Tooltip,
    _bind_hover,
    draw_reticle,
)
from wow_screen import WowScreen

logger = logging.getLogger("Laksefisk")


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
# Main Application Window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()

        # DPI awareness — MUST be before any geometry calls.
        # Without this, GetClientRect/ClientToScreen return wrong values on
        # high-DPI displays, and the tkinter window may resize unexpectedly.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
        except (AttributeError, OSError):
            pass  # shcore not available on older Windows

        # Screen capture
        self._wow_screen = WowScreen()

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
        self._bobber_finder = SearchBobberFinder(self._pc, self._wow_screen)
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
        self._pixel_bridge = PixelBridge(self._wow_screen, scan_region=scan_region)

        # Sound alert state tracking
        self._prev_player_nearby = False
        self._prev_bags_full = False
        self._prev_whisper_flag = 0

        self._bobber_finder.bitmap_callbacks.append(self._on_bitmap_event)

        self._build_ui()
        self._setup_logging()
        self._poll()
        self._check_addon_status()
        self._register_global_hotkeys()

    # ------------------------------------------------------------------
    # Global hotkeys (F6=toggle, F7=pause)
    # ------------------------------------------------------------------

    _HOTKEY_TOGGLE = 1
    _HOTKEY_PAUSE = 2

    def _register_global_hotkeys(self):
        """Register F6/F7 as system-wide hotkeys via Win32 API."""
        def _hotkey_thread():
            user32 = ctypes.windll.user32
            VK_F6 = 0x75
            VK_F7 = 0x76
            MOD_NONE = 0
            try:
                user32.RegisterHotKey(None, self._HOTKEY_TOGGLE, MOD_NONE, VK_F6)
                user32.RegisterHotKey(None, self._HOTKEY_PAUSE, MOD_NONE, VK_F7)
            except Exception:
                return
            msg = ctypes.wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    hotkey_id = msg.wParam
                    if hotkey_id == self._HOTKEY_TOGGLE:
                        self.after(0, self._on_toggle)
                    elif hotkey_id == self._HOTKEY_PAUSE:
                        self.after(0, self._on_pause_click)

        self._hotkey_thread = threading.Thread(target=_hotkey_thread, daemon=True)
        self._hotkey_thread.start()

    # ------------------------------------------------------------------
    # UI layout
    # ------------------------------------------------------------------

    def _build_ui(self):
        """Build PanedWindow layout: status → bobber | fish | log (drag to resize)."""
        self._main_frame = tk.Frame(self, bg=BG_DARK)
        self._main_frame.pack(fill="both", expand=True)

        # Status bar (always at top)
        self._build_status_bar()

        # PanedWindow for drag-resizable panels
        self._paned = ttk.PanedWindow(self._main_frame, orient="vertical")
        self._paned.pack(fill="both", expand=True, padx=2, pady=2)

        # Build panels
        self._build_bobber_view()
        self._build_fish_list()
        self._build_log_panel()

        # Add panels — weights set default proportions (40/20/40)
        self._paned.add(self._bobber_frame, weight=2)
        self._paned.add(self._fish_frame, weight=1)
        self._log_collapsed = self._cfg.get("log_collapsed", False)
        if not self._log_collapsed:
            self._paned.add(self._log_frame, weight=2)

        # Restore saved sash positions
        self._restore_sash_positions()

        # Save config on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Session timer state
        self._session_start = None
        self._session_timer_id = None

    def _build_status_bar(self):
        bar = tk.Frame(self._main_frame, bg=BG_DARK, pady=4, padx=4)
        bar.pack(fill="x")
        self._status_bar = bar

        # Play/stop toggle — canvas-drawn circle
        self._toggle_canvas = tk.Canvas(
            bar, width=32, height=32, bg=BG_DARK,
            highlightthickness=0, cursor="hand2"
        )
        self._toggle_canvas.pack(side="left", padx=(0, 4))
        self._toggle_canvas.bind("<Button-1>", self._on_toggle)
        self._draw_toggle()
        _Tooltip(self._toggle_canvas, "Start/stop fishing (F6)")

        # Pause button (canvas-drawn, initially disabled)
        self._pause_canvas = tk.Canvas(
            bar, width=24, height=24, bg=BG_DARK,
            highlightthickness=0, cursor="hand2"
        )
        self._pause_canvas.pack(side="left", padx=(0, 6))
        self._pause_canvas.bind("<Button-1>", self._on_pause_click)
        self._is_paused = False
        self._draw_pause()
        _Tooltip(self._pause_canvas, "Pause/Resume (F7)")

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
        _Tooltip(self._addon_canvas,
                 "Addon connection status \u2014 green when pixel bridge is active")
        self._addon_label = tk.Label(
            bar, text="No addon", bg=BG_DARK,
            fg=TEXT_DIM, font=("Consolas", 8)
        )
        self._addon_label.pack(side="left", padx=(0, 4))

        # Spacer
        tk.Frame(bar, bg=BG_DARK).pack(side="left", fill="x", expand=True)

        # Session timer
        self._session_label = tk.Label(
            bar, text="00:00:00", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 8)
        )
        self._session_label.pack(side="left", padx=(0, 4))

        # Cal button
        self._cal_btn = tk.Button(
            bar, text="Cal", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
            font=("Consolas", 8), relief="flat", padx=4, pady=1,
            command=self._on_calibrate, cursor="hand2"
        )
        self._cal_btn.pack(side="left", padx=(0, 4))
        _bind_hover(self._cal_btn, PANEL_DEEP, ACCENT, TEXT_PRIMARY, "black")
        _Tooltip(self._cal_btn, "Calibrate bobber colour detection")

        # Gear icon
        gear = tk.Button(
            bar, text="\u2699", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 12), relief="flat", bd=0,
            command=self._on_settings, cursor="hand2"
        )
        gear.pack(side="left")
        _bind_hover(gear, BG_DARK, PANEL_BG, TEXT_DIM, TEXT_PRIMARY)
        _Tooltip(gear, "Open settings")

        # Compact mode toggle
        self._compact_btn = tk.Button(
            bar, text="\u229f", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 10), relief="flat", bd=0,
            command=self._toggle_compact, cursor="hand2"
        )
        self._compact_btn.pack(side="left", padx=(2, 0))
        _bind_hover(self._compact_btn, BG_DARK, PANEL_BG, TEXT_DIM, TEXT_PRIMARY)
        _Tooltip(self._compact_btn, "Toggle compact mode")

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

    def _draw_pause(self):
        self._pause_canvas.delete("all")
        if not self._is_running:
            # Disabled look
            self._pause_canvas.create_oval(1, 1, 23, 23, fill=PANEL_DEEP, outline="")
            self._pause_canvas.create_rectangle(7, 6, 10, 18, fill=TEXT_DIM, outline="")
            self._pause_canvas.create_rectangle(14, 6, 17, 18, fill=TEXT_DIM, outline="")
        elif self._is_paused:
            # Resume icon (green arrow)
            self._pause_canvas.create_oval(1, 1, 23, 23, fill=ACCENT, outline="")
            self._pause_canvas.create_polygon(
                9, 6, 9, 18, 18, 12, fill=BG_DARK, outline=""
            )
        else:
            # Pause icon (yellow bars)
            self._pause_canvas.create_oval(1, 1, 23, 23, fill="#e0c030", outline="")
            self._pause_canvas.create_rectangle(7, 6, 10, 18, fill=BG_DARK, outline="")
            self._pause_canvas.create_rectangle(14, 6, 17, 18, fill=BG_DARK, outline="")

    def _on_toggle(self, _event=None):
        if self._is_running:
            self._on_stop()
        else:
            self._on_play()

    def _on_pause_click(self, _event=None):
        if not self._is_running or not self._bot:
            return
        if self._is_paused:
            self._bot.resume()
            self._is_paused = False
            self._status_var.set("Running")
        else:
            self._bot.pause()
            self._is_paused = True
            self._status_var.set("Paused")
        self._draw_pause()

    def _update_session_timer(self):
        if self._session_start is not None:
            elapsed = int(time.time() - self._session_start)
            h, r = divmod(elapsed, 3600)
            m, s = divmod(r, 60)
            self._session_label.config(text=f"{h:02d}:{m:02d}:{s:02d}", fg=TEXT_PRIMARY)
        self._session_timer_id = self.after(1000, self._update_session_timer)

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
        self._fish_frame = tk.Frame(self._paned, bg=PANEL_BG, height=50)

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
        _Tooltip(self._fish_header_label, "Click to open loot report in browser")
        reset_btn = tk.Button(
            header, text="\u21bb", bg=PANEL_BG, fg=TEXT_DIM,
            font=("Consolas", 10), relief="flat", bd=0,
            command=self._on_reset_fish, cursor="hand2"
        )
        reset_btn.pack(side="right")
        _Tooltip(reset_btn, "Reset fish count for this session")

        # Fish text widget
        self._fish_text = tk.Text(
            self._fish_frame, bg=PANEL_BG, fg=TEXT_PRIMARY,
            font=("Consolas", 9), wrap="none", state="disabled",
            relief="flat", bd=0, padx=4, pady=2,
            selectbackground=PANEL_DEEP, insertbackground=TEXT_PRIMARY
        )
        self._fish_text.pack(fill="both", expand=True)
        self._fish_text.tag_configure("bar", foreground=ACCENT)
        self._fish_text.tag_configure("name", foreground=TEXT_PRIMARY)
        self._fish_text.tag_configure("count", foreground=TEXT_DIM)
        self._fish_text.tag_configure("row_alt", background="#192844")

    def _build_log_panel(self):
        # Log header sits outside PanedWindow so it's always visible
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
        _Tooltip(self._log_chevron, "Collapse/expand log panel")

        # Log content frame goes inside PanedWindow
        self._log_frame = tk.Frame(self._paned, bg=PANEL_BG)
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
            self._paned.add(self._log_frame, weight=2)
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
    # Sash position save / restore
    # ------------------------------------------------------------------

    def _save_sash_positions(self):
        try:
            n = len(self._paned.panes()) - 1
            positions = [self._paned.sashpos(i) for i in range(n)]
            self._cfg["sash_positions"] = positions
        except Exception:
            pass

    def _restore_sash_positions(self):
        def _apply():
            try:
                self.update_idletasks()
                h = self._paned.winfo_height()
                n = len(self._paned.panes()) - 1
                if h > 50 and n >= 2:
                    self._paned.sashpos(0, int(h * 0.4))
                    self._paned.sashpos(1, int(h * 0.6))
            except Exception:
                pass
        # Apply at multiple delays to win against geometry manager
        for delay in (100, 300, 600, 1000):
            self.after(delay, _apply)

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
        self._is_paused = False
        self._draw_toggle()
        self._draw_pause()
        self._status_var.set("Starting...")
        self._amplitude.clear_chart()
        # Start session timer
        self._session_start = time.time()
        self._update_session_timer()
        self._bot_thread = threading.Thread(target=self._bot_thread_func, daemon=True)
        self._bot_thread.start()

    def _on_stop(self):
        if self._bot:
            self._bot.stop()

    def _on_calibrate(self):
        """One-time sweep calibration from current screen."""
        def _run():
            success = sweep_calibrate(self._pc, self._wow_screen)
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
            wow_screen=self._wow_screen,
            lure_key=self._lure_key,
            loot_wait_min=self._loot_min,
            loot_wait_max=self._loot_max,
        )
        self._bot.fishing_event_handler = self._on_fishing_event
        self._bot.fish_tracker = self._fish_tracker
        self._bot.pixel_bridge = self._pixel_bridge
        self._bot.stop_on_friendly_nearby = self._cfg.get("stop_on_friendly", False)
        self._bot.stop_on_enemy_nearby = self._cfg.get("stop_on_enemy", False)
        self._bot.stop_on_bags_full = self._cfg.get("stop_on_bags", False)
        self._bot.auto_calibrate = self._cfg.get("auto_calibrate", False)
        self._bot.auto_delete_junk = self._cfg.get("auto_delete_junk", False)
        self._bot.debug_screenshots = self._cfg.get("debug_screenshots", False)
        self._bot._pixel_classifier = self._pc
        self._bot.start()

        self._bot = None
        self.after(0, self._on_bot_stopped)

    def _on_bot_stopped(self):
        self._is_running = False
        self._is_paused = False
        self._draw_toggle()
        self._draw_pause()
        self._status_var.set("Idle")
        self._flying_fish.stop()
        self._hide_loot()
        # Stop session timer (keep display showing final time)
        if self._session_timer_id:
            self.after_cancel(self._session_timer_id)
            self._session_timer_id = None

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

        for i, (name, count, pct) in enumerate(stats):
            bar_len = int(pct / 5)
            bar = "\u2588" * bar_len
            line_start = self._fish_text.index("end-1c")
            self._fish_text.insert("end", bar, "bar")
            self._fish_text.insert("end", f" {pct:4.1f}%  ", "count")
            self._fish_text.insert("end", f"{name}", "name")
            self._fish_text.insert("end", f"  x{count}\n", "count")
            if i % 2 == 1:
                line_end = self._fish_text.index("end-1c")
                self._fish_text.tag_add("row_alt", line_start, line_end)

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

        self.after(self._pixel_bridge.poll_interval_ms, self._check_addon_status)

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
        # Don't read live -topmost attribute — it's temporarily disabled
        # while the settings popup is open.  Use the cfg value instead.
        self._cfg.setdefault("always_on_top", True)
        self._cfg["sound_alerts"] = self._cfg.get("sound_alerts", False)
        self._cfg["pixel_bar_region"] = self._cfg.get("pixel_bar_region")
        if self._bot:
            self._cfg["stop_on_friendly"] = self._bot.stop_on_friendly_nearby
            self._cfg["stop_on_enemy"] = self._bot.stop_on_enemy_nearby
            self._cfg["stop_on_bags"] = self._bot.stop_on_bags_full
            self._cfg["auto_calibrate"] = self._bot.auto_calibrate
            self._cfg["auto_delete_junk"] = self._bot.auto_delete_junk
        # Don't save compact-mode window size
        if not (hasattr(self, "_compact_active") and self._compact_active):
            self._cfg["window_width"] = self.winfo_width()
            self._cfg["window_height"] = self.winfo_height()
            self._save_sash_positions()
        _save_config(self._cfg)

    def _on_close(self):
        # Capture sash positions and geometry BEFORE anything gets destroyed
        if hasattr(self, "_compact_active") and self._compact_active:
            self._cfg["compact_mode"] = False
            if hasattr(self, "_saved_geometry") and self._saved_geometry:
                m = re.match(r"(\d+)x(\d+)", self._saved_geometry)
                if m:
                    self._cfg["window_width"] = int(m.group(1))
                    self._cfg["window_height"] = int(m.group(2))
        else:
            self._cfg["window_width"] = self.winfo_width()
            self._cfg["window_height"] = self.winfo_height()
            self._save_sash_positions()
        # Save all other config
        self._cfg["cast_key"] = self._cast_key
        self._cfg["lure_key"] = self._lure_key
        self._cfg["loot_wait_min"] = self._loot_min
        self._cfg["loot_wait_max"] = self._loot_max
        self._cfg["colour_mode"] = "Red" if self._pc.mode == ClassifierMode.Red else "Blue"
        self._cfg["colour_multiplier"] = self._pc.colour_multiplier
        self._cfg["colour_closeness_multiplier"] = self._pc.colour_closeness_multiplier
        self._cfg["bite_sensitivity"] = self._bite_sensitivity
        self._cfg["log_collapsed"] = self._log_collapsed
        self._cfg["always_on_top"] = self._cfg.get("always_on_top", True)
        if self._bot:
            self._cfg["stop_on_friendly"] = self._bot.stop_on_friendly_nearby
            self._cfg["stop_on_enemy"] = self._bot.stop_on_enemy_nearby
            self._cfg["stop_on_bags"] = self._bot.stop_on_bags_full
            self._cfg["auto_calibrate"] = self._bot.auto_calibrate
            self._cfg["auto_delete_junk"] = self._bot.auto_delete_junk
        _save_config(self._cfg)
        if self._bot:
            self._bot.stop()
        self.destroy()

    def _on_settings(self):
        SettingsPopup(self, on_change=lambda: None)

    # ------------------------------------------------------------------
    # Compact mode
    # ------------------------------------------------------------------

    def _toggle_compact(self):
        is_compact = hasattr(self, "_compact_active") and self._compact_active
        if is_compact:
            self._exit_compact()
        else:
            self._enter_compact()

    def _enter_compact(self):
        self._compact_active = True
        self._cfg["compact_mode"] = True
        self._saved_geometry = self.geometry()
        self._save_sash_positions()

        # Hide PanedWindow and log header
        self._paned.pack_forget()
        self._log_header.pack_forget()

        # Build compact info frame
        self._compact_frame = tk.Frame(self._main_frame, bg=BG_DARK)
        self._compact_frame.pack(fill="x", padx=4)

        # Fish count
        total = self._fish_tracker.total if self._fish_tracker else 0
        self._compact_fish_label = tk.Label(
            self._compact_frame, text=f"{total} fish", bg=BG_DARK,
            fg=TEXT_PRIMARY, font=("Consolas", 9)
        )
        self._compact_fish_label.pack(side="left", padx=(0, 8))

        # Expand button
        expand_btn = tk.Button(
            self._compact_frame, text="\u25a1 Expand", bg=PANEL_DEEP, fg=TEXT_PRIMARY,
            font=("Consolas", 8), relief="flat", padx=4, pady=1,
            command=self._exit_compact, cursor="hand2"
        )
        expand_btn.pack(side="right")
        _bind_hover(expand_btn, PANEL_DEEP, ACCENT, TEXT_PRIMARY, "black")

        # Resize window — override minsize for compact
        self.minsize(200, 50)
        self.geometry("300x50")
        self.resizable(False, False)

        self._compact_btn.config(text="\u229e")
        self._save_cfg()

    def _exit_compact(self):
        self._compact_active = False
        self._cfg["compact_mode"] = False

        # Destroy compact frame
        if hasattr(self, "_compact_frame"):
            self._compact_frame.destroy()

        # Restore PanedWindow and log header
        self._log_header.pack(fill="x", side="bottom")
        self._paned.pack(fill="both", expand=True, padx=2, pady=2)
        self._restore_sash_positions()

        self.minsize(160, 300)
        self.resizable(True, True)
        if hasattr(self, "_saved_geometry") and self._saved_geometry:
            self.geometry(self._saved_geometry)
        else:
            w = self._cfg.get("window_width", 200)
            h = self._cfg.get("window_height", 500)
            self.geometry(f"{w}x{h}")
        self._compact_btn.config(text="\u229f")
        self._save_cfg()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = App()
    app.mainloop()
