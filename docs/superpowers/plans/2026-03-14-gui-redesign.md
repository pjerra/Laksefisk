# GUI Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the light-themed horizontal GUI with a dark-themed, dockable, resizable Layout H (vertical) / Layout F (horizontal) adaptive interface.

**Architecture:** Rewrite `gui.py` in-place, keeping the same file. Extract theme constants, rebuild `App._build_ui()` with new layout, refactor `BobberChart` into an overlay renderer, merge `ColourConfigWindow` into a unified settings popup. All other modules (bot, pixel bridge, fish tracker, etc.) remain untouched.

**Tech Stack:** Python 3, tkinter, ttk, PIL/Pillow, mss

**Spec:** `docs/superpowers/specs/2026-03-14-gui-redesign-design.md`

---

## File Structure

All changes happen in a single file:

- **Modify:** `gui.py` (1245 lines → ~1400 lines estimated)
  - Replace colour constants (lines 77–86)
  - Refactor `BobberChart` class (lines 117–192) → `AmplitudeOverlay` helper
  - Keep `FlyingFishOverlay` (lines 198–248) — update canvas reference
  - Keep `_Tooltip` (lines 254–279) — update colours
  - Rewrite `ColourConfigWindow` (lines 281–647) → `SettingsPopup`
  - Rewrite `App._build_ui` (lines 721–927) — new layout
  - Update `App._update_screenshot` (lines 1128–1145) — add zoom crop
  - Update `App._update_fish_display` (lines 1078–1095) — canvas-based bars
  - Add dock detection and layout switching logic
  - Update `DEFAULT_CONFIG` (lines 47–55) — add new keys

No new files created. No other existing files modified.

---

## Chunk 1: Theme and Foundation

### Task 1: Replace colour constants and update DEFAULT_CONFIG

**Files:**
- Modify: `gui.py:47–55` (DEFAULT_CONFIG)
- Modify: `gui.py:77–86` (colour constants)

- [ ] **Step 1: Replace colour constants**

Replace lines 77–86 in `gui.py`:

```python
# Old light-theme constants — REMOVE these:
# BG_WHITE, LIGHT_BLUE, CARD_BG, TEXT_DARK, TEXT_GREY,
# CHART_RED, CHART_BLUE_FILL, CHART_GRID

# Dark theme
BG_DARK = "#1a1a2e"
PANEL_BG = "#16213e"
PANEL_DEEP = "#0f3460"
ACCENT = "#00d4aa"
ALERT = "#e94560"
TEXT_PRIMARY = "#cccccc"
TEXT_DIM = "#555555"
```

- [ ] **Step 2: Update DEFAULT_CONFIG with new keys**

Add to `DEFAULT_CONFIG` dict (lines 47–55):

```python
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
```

- [ ] **Step 3: Update all old colour references throughout gui.py**

Find-and-replace throughout the file:
- `BG_WHITE` → `BG_DARK`
- `LIGHT_BLUE` → `ACCENT`
- `CARD_BG` → `PANEL_BG`
- `TEXT_DARK` → `TEXT_PRIMARY`
- `TEXT_GREY` → `TEXT_DIM`
- `CHART_RED` → `ALERT`
- `CHART_BLUE_FILL` → `PANEL_DEEP`
- `CHART_GRID` → `PANEL_DEEP`

Also update any hardcoded `bg="white"`, `bg="#FFFFFF"`, `fg="black"` etc. to use the new tokens.

- [ ] **Step 4: Run the app to verify it launches with new colours**

```bash
cd C:\Users\perzi\laksefisk && python gui.py
```

Expected: App launches with dark background. Layout may look rough (old layout + new colours), but no crashes.

- [ ] **Step 5: Commit**

```bash
git add gui.py
git commit -m "feat(gui): replace light theme with dark colour tokens"
```

---

### Task 2: Add AmplitudeOverlay class (keep BobberChart until Task 3)

Add the new `AmplitudeOverlay` class alongside `BobberChart`. Do NOT delete `BobberChart` yet — it's still referenced by `_build_ui` until Task 3 replaces it.

**Files:**
- Modify: `gui.py` — add new class after `BobberChart` (after line 192)

- [ ] **Step 1: Add AmplitudeOverlay class after BobberChart**

Insert after line 192 (after `BobberChart` class, before `FlyingFishOverlay`):

```python
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
        # Remove old overlay items
        for item_id in self._item_ids:
            self._canvas.delete(item_id)
        self._item_ids.clear()

        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 10 or h < 10:
            return

        # Overlay occupies bottom 20%
        overlay_h = int(h * 0.2)
        overlay_top = h - overlay_h

        # Gradient background (semi-transparent effect via dark rectangle)
        bg_id = self._canvas.create_rectangle(
            0, overlay_top, w, h,
            fill=BG_DARK, stipple="gray50", outline=""
        )
        self._item_ids.append(bg_id)

        if len(self._data) < 2:
            return

        now = time.time()
        window = 20  # 20 seconds max
        y_min, y_max = -15, 10
        y_range = y_max - y_min
        bar_w = 3
        gap = 1

        for t, v in self._data:
            elapsed = now - t
            if elapsed > window:
                continue
            x = int(w - (elapsed / window) * w)
            # Map value to bar height within overlay
            norm = (v - y_min) / y_range  # 0..1
            bar_h = int(norm * overlay_h)
            bar_h = max(1, min(bar_h, overlay_h))

            colour = ALERT if v <= -self._strike else PANEL_DEEP
            bar_id = self._canvas.create_rectangle(
                x - bar_w, h - bar_h, x, h,
                fill=colour, outline=""
            )
            self._item_ids.append(bar_id)

        # Strike threshold line (dashed)
        strike_norm = (-self._strike - y_min) / y_range
        strike_y = overlay_top + overlay_h - int(strike_norm * overlay_h)
        if overlay_top <= strike_y <= h:
            line_id = self._canvas.create_line(
                0, strike_y, w, strike_y,
                fill=TEXT_DIM, dash=(4, 4)
            )
            self._item_ids.append(line_id)
```

- [ ] **Step 2: Verify the class has no syntax errors**

```bash
cd C:\Users\perzi\laksefisk && python -c "import gui; print('OK')"
```

Expected: OK (no import errors). `BobberChart` still exists, `AmplitudeOverlay` is new.

- [ ] **Step 3: Commit**

```bash
git add gui.py
git commit -m "feat(gui): add AmplitudeOverlay class for bobber view overlay"
```

---

### Task 3: Rewrite App.__init__ and _build_ui — Status Bar + Bobber View

This is the core layout rewrite. We replace the 3-column horizontal layout with a vertical stack that can switch to horizontal.

**Files:**
- Modify: `gui.py:653–927` (App.__init__ and _build_ui)

- [ ] **Step 1: Rewrite App.__init__**

Keep the existing init logic (mss warm-up, config load, component init) but change the window geometry:

```python
def __init__(self):
    super().__init__()
    # mss DPI warm-up — MUST be before any geometry calls
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
    self._dock_mode = dock  # "left", "top", "right", "floating"
    self._layout_mode = "horizontal" if dock == "top" else "vertical"
    self._configure_after_id = None  # debounce timer for dock detection

    # ... rest of existing init: PixelClassifier, bobber finder,
    # bite watcher, fish tracker, pixel bridge, bot vars, log queue ...
    # (keep all of lines ~670–709 from current code)
```

Keep all the existing component initialization (PixelClassifier, SearchBobberFinder, PositionBiteWatcher, FishTracker, PixelBridge, bot vars, log queue, screenshot photo). Just change the window setup at the top.

- [ ] **Step 2: Write new _build_ui — vertical layout**

Replace `_build_ui` (lines 721–927). Build the vertical stack:

```python
def _build_ui(self):
    """Build adaptive layout — vertical stack or horizontal row."""
    # Main container
    self._main_frame = tk.Frame(self, bg=BG_DARK)
    self._main_frame.pack(fill="both", expand=True)

    # Build the status bar (always at top)
    self._build_status_bar()

    # PanedWindow for resizable panels
    self._paned = ttk.PanedWindow(self._main_frame, orient="vertical")
    self._paned.pack(fill="both", expand=True, padx=2, pady=2)

    # Bobber view panel
    self._build_bobber_view()

    # Fish list panel
    self._build_fish_list()

    # Log panel
    self._build_log_panel()

    # Add panels to paned window
    self._paned.add(self._bobber_frame, weight=3)
    self._paned.add(self._fish_frame, weight=2)
    self._paned.add(self._log_frame, weight=1)

    # Bind resize for dock detection
    self.bind("<Configure>", self._on_configure)

    # Setup logging and polling (addon status check added in Task 9)
    self._setup_logging()
    self._poll()

    # Save config on close
    self.protocol("WM_DELETE_WINDOW", self._on_close)
```

- [ ] **Step 3: Write _build_status_bar**

```python
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
    self._is_running = False
    self._draw_toggle()

    # Status text
    self._status_var = tk.StringVar(value="Idle")
    tk.Label(
        bar, textvariable=self._status_var, bg=BG_DARK,
        fg=ACCENT, font=("Consolas", 9)
    ).pack(side="left", padx=(0, 4))

    # Addon dot
    self._addon_canvas = tk.Canvas(
        bar, width=10, height=10, bg=BG_DARK, highlightthickness=0
    )
    self._addon_canvas.pack(side="left", padx=(0, 4))
    self._addon_dot = self._addon_canvas.create_oval(1, 1, 9, 9, fill=TEXT_DIM)
    _Tooltip(self._addon_canvas, "Addon: Not found")

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
        # Red circle + stop square
        self._toggle_canvas.create_oval(2, 2, 22, 22, fill=ALERT, outline="")
        self._toggle_canvas.create_rectangle(8, 8, 16, 16, fill=BG_DARK, outline="")
    else:
        # Teal circle + play triangle
        self._toggle_canvas.create_oval(2, 2, 22, 22, fill=ACCENT, outline="")
        self._toggle_canvas.create_polygon(
            10, 7, 10, 17, 18, 12, fill=BG_DARK, outline=""
        )

def _on_toggle(self, _event=None):
    if self._is_running:
        self._on_stop()
    else:
        self._on_play()
```

- [ ] **Step 4: Write _build_bobber_view**

```python
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
        0, 32, text="", fill=BG_DARK, font=("Consolas", 14, "bold"), anchor="n"
    )
    self._loot_id = self._screenshot_canvas.create_text(
        0, 30, text="", fill=TEXT_PRIMARY, font=("Consolas", 14, "bold"), anchor="n"
    )

    self._screenshot_canvas.bind("<Configure>", self._on_ss_resize)
```

- [ ] **Step 5: Run the app to verify status bar and bobber view render**

```bash
cd C:\Users\perzi\laksefisk && python gui.py
```

Expected: Dark window with status bar (play button, Idle text, addon dot, Cal, gear). Black bobber view below. May crash if fish/log panels aren't built yet — that's the next step.

- [ ] **Step 6: Commit**

```bash
git add gui.py
git commit -m "feat(gui): new dark layout — status bar and bobber view"
```

---

### Task 4: Fish List and Log Panels

**Files:**
- Modify: `gui.py` — add `_build_fish_list` and `_build_log_panel` methods

- [ ] **Step 1: Write _build_fish_list**

```python
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
```

- [ ] **Step 2: Write _build_log_panel**

```python
def _build_log_panel(self):
    self._log_frame = tk.Frame(self._paned, bg=PANEL_BG)
    self._log_collapsed = self._cfg.get("log_collapsed", False)

    # Header
    header = tk.Frame(self._log_frame, bg=PANEL_BG, pady=2, padx=4)
    header.pack(fill="x")
    tk.Label(
        header, text="Log", bg=PANEL_BG, fg=TEXT_DIM,
        font=("Consolas", 9)
    ).pack(side="left")
    self._log_chevron = tk.Label(
        header, text="\u25b2" if self._log_collapsed else "\u25bc",
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
    if not self._log_collapsed:
        self._log_text.pack(fill="both", expand=True)

def _toggle_log(self, _event=None):
    self._log_collapsed = not self._log_collapsed
    self._log_chevron.config(
        text="\u25b2" if self._log_collapsed else "\u25bc"
    )
    if self._log_collapsed:
        # Remove log pane from PanedWindow (pack_forget doesn't work
        # inside ttk.PanedWindow — must use .forget())
        self._paned.forget(self._log_frame)
    else:
        self._paned.add(self._log_frame, weight=1)
    self._save_cfg()
```

- [ ] **Step 3: Run the app to verify full vertical layout**

```bash
cd C:\Users\perzi\laksefisk && python gui.py
```

Expected: Dark window with status bar → bobber view → fish list → collapsible log. All panels visible with sash dividers.

- [ ] **Step 4: Commit**

```bash
git add gui.py
git commit -m "feat(gui): add fish list and collapsible log panels"
```

---

## Chunk 2: Bobber Zoom, Screenshot Update, and Fish Display

### Task 5: Add bobber zoom to _update_screenshot

**Files:**
- Modify: `gui.py` — `_update_screenshot` method (lines 1128–1145)

- [ ] **Step 1: Rewrite _update_screenshot with zoom crop**

Keep the existing two-argument signature (`img, point`) to match `_on_bitmap_event` which calls `self._update_screenshot(img, point)`:

```python
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
        # Re-clamp if hitting right/bottom edge
        x1 = max(0, x2 - crop_w)
        y1 = max(0, y2 - crop_h)
        img = img.crop((x1, y1, x2, y2))
        # Adjust reticle point to crop coordinates
        reticle_x = cx - x1
        reticle_y = cy - y1
        img = draw_reticle(img, (reticle_x, reticle_y))
    else:
        img = draw_reticle(img, point)

    # Scale to canvas
    cw = self._screenshot_canvas.winfo_width()
    ch = self._screenshot_canvas.winfo_height()
    if cw < 10 or ch < 10:
        del img  # PIL Image has no .close(); let GC handle it
        return

    iw, ih = img.size
    scale = min(cw / iw, ch / ih)
    new_w = max(1, int(iw * scale))
    new_h = max(1, int(ih * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    self._screenshot_photo = ImageTk.PhotoImage(img)
    self._screenshot_canvas.coords(self._ss_img_id, cw // 2, ch // 2)
    self._screenshot_canvas.itemconfig(self._ss_img_id, image=self._screenshot_photo)
    del img  # PIL Image has no .close(); let GC handle it

    # Redraw amplitude overlay on top
    self._amplitude.draw()
```

- [ ] **Step 2: Verify zoom works visually**

Run the app, start the bot with WoW open. When bobber is found, the view should zoom in ~3x centred on the bobber with reticle overlay. When no bobber found, full scan area shown.

- [ ] **Step 3: Commit**

```bash
git add gui.py
git commit -m "feat(gui): add bobber zoom crop to screenshot view"
```

---

### Task 6: Update _update_fish_display for dark theme

**Files:**
- Modify: `gui.py` — `_update_fish_display` method (lines 1078–1095)

- [ ] **Step 1: Update fish display rendering**

The existing `_update_fish_display` method should already work with the new tag colours set in Task 4. Verify the tags are correct:

```python
def _update_fish_display(self):
    # FishTracker.get_stats() returns list of (name, count, pct) tuples
    stats = self._fish_tracker.get_stats()
    total = self._fish_tracker.total
    self._fish_header_label.config(text=f"Fish Caught ({total})")

    self._fish_text.configure(state="normal")
    self._fish_text.delete("1.0", "end")
    for name, count, pct in stats:
        bar_len = int(pct / 5)  # max 20 blocks at 100%
        bar = "\u2588" * bar_len
        self._fish_text.insert("end", bar, "bar")
        self._fish_text.insert("end", f" {pct:4.1f}%  ", "count")
        self._fish_text.insert("end", f"{name}", "name")
        self._fish_text.insert("end", f"  x{count}\n", "count")
    self._fish_text.configure(state="disabled")
```

- [ ] **Step 2: Run and verify fish display looks correct with dark theme**

Start the bot briefly or check with test data. Fish bars should appear in `PANEL_DEEP` colour, names in `TEXT_PRIMARY`, counts in `TEXT_DIM`.

- [ ] **Step 3: Commit**

```bash
git add gui.py
git commit -m "feat(gui): update fish display for dark theme"
```

---

## Chunk 3: Settings Popup and Dock Logic

### Task 7: Create SettingsPopup replacing ColourConfigWindow

**Files:**
- Modify: `gui.py:281–647` (replace ColourConfigWindow)

- [ ] **Step 1: Write SettingsPopup class**

Replace `ColourConfigWindow` with a unified `SettingsPopup`:

```python
class SettingsPopup(tk.Toplevel):
    """Unified settings popup — dark themed."""

    def __init__(self, parent: "App", on_change: callable):
        super().__init__(parent)
        self.title("Settings")
        self.configure(bg=BG_DARK)
        self.geometry("400x550")
        self.attributes("-topmost", True)
        self.resizable(True, True)
        self._parent = parent
        self._on_change = on_change
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _build(self):
        container = tk.Frame(self, bg=BG_DARK, padx=12, pady=8)
        container.pack(fill="both", expand=True)

        row = 0
        # --- Cast Key ---
        self._add_label(container, "Cast Key", row)
        self._cast_var = tk.StringVar(value=hex(self._parent._cast_key))
        e = tk.Entry(
            container, textvariable=self._cast_var, bg=PANEL_BG,
            fg=TEXT_PRIMARY, font=("Consolas", 10), insertbackground=TEXT_PRIMARY,
            relief="flat", width=8
        )
        e.grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        e.bind("<KeyRelease>", lambda _: self._on_cast_key())
        row += 1

        # --- Lure Key ---
        self._add_label(container, "Lure Key", row)
        lure = self._parent._lure_key
        self._lure_var = tk.StringVar(value=hex(lure) if lure else "None")
        e = tk.Entry(
            container, textvariable=self._lure_var, bg=PANEL_BG,
            fg=TEXT_PRIMARY, font=("Consolas", 10), insertbackground=TEXT_PRIMARY,
            relief="flat", width=8
        )
        e.grid(row=row, column=1, sticky="ew", pady=2, padx=(4, 0))
        e.bind("<KeyRelease>", lambda _: self._on_lure_key())
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
            value=self._parent._cfg.get("colour_mode", "Red")
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
        self._mult_var = tk.DoubleVar(
            value=self._parent._pc.colour_multiplier
        )
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

        container.columnconfigure(1, weight=1)

    def _add_label(self, parent, text, row):
        tk.Label(
            parent, text=text, bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 9), anchor="w"
        ).grid(row=row, column=0, sticky="w", pady=2)

    def _on_cast_key(self):
        try:
            val = int(self._cast_var.get(), 16)
            self._parent._cast_key = val
            if self._parent._bot:
                self._parent._bot.set_cast_key(val)
            self._parent._save_cfg()
        except ValueError:
            pass

    def _on_lure_key(self):
        raw = self._lure_var.get().strip()
        if raw.lower() == "none" or raw == "":
            self._parent._lure_key = None
        else:
            try:
                self._parent._lure_key = int(raw, 16)
            except ValueError:
                return
        if self._parent._bot:
            self._parent._bot.set_lure_key(self._parent._lure_key)
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
        # Sync instance attributes with reset config
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
        self._parent._on_settings()  # reopen with reset values
```

- [ ] **Step 2: Update App._on_settings to use SettingsPopup**

```python
def _on_settings(self):
    SettingsPopup(self, on_change=lambda: None)
```

- [ ] **Step 3: Add expandable colour preview section to SettingsPopup**

Add an expandable section at the bottom of `SettingsPopup._build()` that contains the capture preview and colour map from the old `ColourConfigWindow`. This preserves the spec requirement to move this content into the unified popup:

```python
        # --- Expandable: Colour Preview ---
        row += 1
        self._preview_expanded = False
        self._preview_btn = tk.Button(
            container, text="\u25b6 Colour Preview", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 9), relief="flat", anchor="w",
            command=self._toggle_preview, cursor="hand2"
        )
        self._preview_btn.grid(row=row, column=0, columnspan=2, sticky="w", pady=(8, 0))
        row += 1

        self._preview_frame = tk.Frame(container, bg=BG_DARK)
        # Not gridded yet — shown on expand

        # Inside preview_frame: capture button, live toggle, preview canvas
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
            btn_row, text="Matches: —", bg=BG_DARK, fg=TEXT_DIM,
            font=("Consolas", 8)
        )
        self._match_label.pack(side="right")

        self._preview_canvas = tk.Canvas(
            self._preview_frame, bg="black", width=400, height=200,
            highlightthickness=0
        )
        self._preview_canvas.pack(fill="both", expand=True)
        self._preview_img_id = self._preview_canvas.create_image(0, 0, anchor="nw")
        self._preview_photo = None
        self._live_timer = None
        self._preview_row = row

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
            from wow_screen import WowScreen
            img = WowScreen.get_bitmap()
            pc = self._parent._pc
            iw, ih = img.size
            pixels = img.load()
            matches = 0
            for y in range(0, ih, 2):
                for x in range(0, iw, 2):
                    r, g, b = pixels[x, y]
                    if pc.is_match(r, g, b):
                        matches += 1
                        pixels[x, y] = (255, 0, 0) if pc.mode == ClassifierMode.Red else (0, 0, 255)
            self._match_label.config(text=f"Matches: {matches}")
            # Scale to canvas
            cw, ch = 400, 200
            img = img.resize((cw, ch), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(img)
            self._preview_canvas.itemconfig(self._preview_img_id, image=self._preview_photo)
        except Exception as e:
            self._match_label.config(text=f"Error: {e}")
```

- [ ] **Step 4: Remove the old ColourConfigWindow class**

Delete lines 281–647 (the entire `ColourConfigWindow` class). The capture preview and colour detection functionality is now in `SettingsPopup._render_preview()`.

- [ ] **Step 5: Run and verify settings popup opens and works**

```bash
cd C:\Users\perzi\laksefisk && python gui.py
```

Click gear icon → settings popup should open with all controls. Test changing values. Expand "Colour Preview" section, click Capture → should show screen capture with matched pixels highlighted.

- [ ] **Step 6: Commit**

```bash
git add gui.py
git commit -m "feat(gui): unified dark settings popup replacing ColourConfigWindow"
```

---

### Task 8: Dock detection and layout switching

**Files:**
- Modify: `gui.py` — add dock logic to App

- [ ] **Step 1: Add _on_configure for dock detection**

```python
_SNAP_THRESHOLD = 20

def _on_configure(self, event=None):
    """Detect dock position based on window location (debounced)."""
    if event and event.widget != self:
        return
    # Debounce: cancel pending check, reschedule 100ms later
    if hasattr(self, "_configure_after_id") and self._configure_after_id:
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
        new_layout = self._layout_mode  # keep current

    self._dock_mode = new_dock

    if new_layout != old_mode:
        self._layout_mode = new_layout
        self._rebuild_layout()
```

- [ ] **Step 2: Add _rebuild_layout for switching between vertical/horizontal**

```python
def _rebuild_layout(self):
    """Destroy and rebuild paned window with new orientation."""
    # Save current sash positions
    self._save_sash_positions()

    # Remove paned window
    self._paned.destroy()

    if self._layout_mode == "horizontal":
        self._paned = ttk.PanedWindow(self._main_frame, orient="horizontal")
        self.minsize(400, 90)
    else:
        self._paned = ttk.PanedWindow(self._main_frame, orient="vertical")
        self.minsize(160, 300)

    self._paned.pack(fill="both", expand=True, padx=2, pady=2)

    # Recreate panel frames inside new paned window
    # (tkinter .master is read-only — cannot re-parent widgets)
    self._build_bobber_view()
    self._build_fish_list()
    self._build_log_panel()

    self._paned.add(self._bobber_frame, weight=3)
    self._paned.add(self._fish_frame, weight=2)
    if not self._log_collapsed:
        self._paned.add(self._log_frame, weight=1)

    # Restore sash positions for this mode
    self._restore_sash_positions()

    # Re-render fish display if we have data
    self._update_fish_display()

def _save_sash_positions(self):
    try:
        positions = [self._paned.sashpos(i) for i in range(2)]
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
        for i, pos in enumerate(positions):
            self._paned.sashpos(i, pos)
    except Exception:
        pass
```

- [ ] **Step 3: Add _apply_dock for settings-driven dock change**

```python
def _apply_dock(self, dock: str):
    """Move window to dock position."""
    self._dock_mode = dock
    sw = self.winfo_screenwidth()
    sh = self.winfo_screenheight()
    w = self._cfg.get("window_width", 200)
    h = self._cfg.get("window_height", 500)

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
    else:  # floating
        self.geometry(f"{w}x{h}")

    self._rebuild_layout()
```

- [ ] **Step 4: Test dock behaviour**

Run the app. Drag to left edge → should snap and go vertical. Drag to top → should switch to horizontal layout. Use settings dropdown to change dock position.

- [ ] **Step 5: Commit**

```bash
git add gui.py
git commit -m "feat(gui): dock detection and vertical/horizontal layout switching"
```

---

## Chunk 4: Wire Up Remaining Logic and Config Save

### Task 9: Wire up _on_play, _on_stop, _bot_thread_func, event handlers

These methods mostly stay the same but need minor updates for the new UI widgets.

**Files:**
- Modify: `gui.py` — update App methods

- [ ] **Step 1: Update _on_play and _on_stop for toggle button**

```python
def _on_play(self):
    if self._bot_thread and self._bot_thread.is_alive():
        return
    self._is_running = True
    self._draw_toggle()
    self._status_var.set("Running")
    self._amplitude.clear_chart()
    self._bot_thread = threading.Thread(target=self._bot_thread_func, daemon=True)
    self._bot_thread.start()

def _on_stop(self):
    if self._bot:
        self._bot.stop()

def _on_bot_stopped(self):
    self._is_running = False
    self._draw_toggle()
    self._status_var.set("Idle")
    self._flying_fish.stop()

# Note: "Paused" (yellow) status is set by the bot when player nearby
# is detected. The bot calls fishing_event_handler with a Cast event
# and the _check_stop_conditions loop in fishing_bot.py handles the
# paused state. If we want to show "Paused" in the GUI, add a new
# FishingAction.Paused event and handle it in _handle_event:
#   elif event.action == FishingAction.Paused:
#       self._status_var.set("Paused")
#       self._status_label.config(fg="#f0c040")  # yellow
# This requires adding FishingAction.Paused to models.py — defer to later.
```

- [ ] **Step 2: Update _handle_event for AmplitudeOverlay**

```python
def _handle_event(self, event: FishingEvent):
    if event.action == FishingAction.BobberMove:
        self._amplitude.add(event.amplitude)  # .amplitude, not .value
    elif event.action == FishingAction.Loot:
        self._show_loot()  # no arguments (matches existing signature)
        self._flying_fish.start()
        self._update_fish_display()
    elif event.action == FishingAction.Cast:
        self._hide_loot()
        self._amplitude.clear_chart()
        self._flying_fish.stop()
```

- [ ] **Step 3: Update _check_addon_status for addon dot and start it**

```python
def _check_addon_status(self):
    try:
        data = self._pixel_bridge.read()
        connected = data is not None
    except Exception:
        connected = False

    colour = ACCENT if connected else TEXT_DIM
    self._addon_canvas.itemconfig(self._addon_dot, fill=colour)

    self.after(2000, self._check_addon_status)
```

Also add the initial call in `_build_ui` (or at end of `__init__`):
```python
# At end of App.__init__, after _build_ui():
self._check_addon_status()
```

- [ ] **Step 4: Update _save_cfg with new config keys**

```python
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
    # Capture current window dimensions
    self._cfg["window_width"] = self.winfo_width()
    self._cfg["window_height"] = self.winfo_height()
    self._save_sash_positions()
    _save_config(self._cfg)

def _on_close(self):
    self._save_cfg()
    if self._bot:
        self._bot.stop()
    self.destroy()
```

- [ ] **Step 5: Update _bot_thread_func**

Keep existing bot creation logic but update references to match new widget names. The key changes:
- Replace `self._btn_play.config(state="disabled")` → nothing (toggle handles it)
- Replace `self._btn_stop.config(state="normal")` → nothing
- Set `bot.stop_on_player_nearby = self._cfg.get("stop_on_player", False)`
- Set `bot.stop_on_bags_full = self._cfg.get("stop_on_bags", False)`
- Set `bot.auto_calibrate = self._cfg.get("auto_calibrate", False)`
- Call `self.after(0, self._on_bot_stopped)` when thread ends

- [ ] **Step 6: Run full integration test**

```bash
cd C:\Users\perzi\laksefisk && python gui.py
```

Test: start/stop bot, verify amplitude overlay, fish list updates, log entries, settings popup, dock switching.

- [ ] **Step 7: Commit**

```bash
git add gui.py
git commit -m "feat(gui): wire up bot controls, events, and config persistence"
```

---

### Task 10: Clean up — remove old code, final polish

**Files:**
- Modify: `gui.py` — remove dead code

- [ ] **Step 1: Remove old colour constants**

Verify no references remain to: `BG_WHITE`, `LIGHT_BLUE`, `CARD_BG`, `TEXT_DARK`, `TEXT_GREY`, `CHART_RED`, `CHART_BLUE_FILL`, `CHART_GRID`. Delete if still present.

- [ ] **Step 2: Remove old BobberChart class if still present**

Should already be replaced by `AmplitudeOverlay`. Verify and remove any remnants.

- [ ] **Step 3: Remove standalone _on_cast_key_entry, _on_lure_key_entry, _on_loot_delay_change from App**

These are now handled inside `SettingsPopup`. Remove the old methods from `App` if they're still there.

- [ ] **Step 4: Remove _keysym_to_vk and _vk_to_label if unused**

Check if these are still needed. If not, remove.

- [ ] **Step 5: Run final test**

```bash
cd C:\Users\perzi\laksefisk && python gui.py
```

Full test: launch → dark theme → start bot → see zoomed bobber → amplitude overlay → fish list → log → settings popup → dock left → dock top (horizontal) → dock right → floating → close (config saved).

- [ ] **Step 6: Commit**

```bash
git add gui.py
git commit -m "refactor(gui): remove dead code from old light-theme layout"
```

---

## Summary

| Task | Description | Estimated Steps |
|------|-------------|----------------|
| 1 | Theme constants + DEFAULT_CONFIG | 5 |
| 2 | AmplitudeOverlay class (keep BobberChart) | 3 |
| 3 | Status bar + bobber view layout | 6 |
| 4 | Fish list + log panels (collapsible) | 4 |
| 5 | Bobber zoom crop | 3 |
| 6 | Fish display dark theme | 3 |
| 7 | SettingsPopup + colour preview | 6 |
| 8 | Dock detection + layout switching (debounced) | 5 |
| 9 | Wire up bot/events/config/addon status | 7 |
| 10 | Cleanup dead code (remove BobberChart, old constants) | 6 |
| **Total** | | **48 steps** |
