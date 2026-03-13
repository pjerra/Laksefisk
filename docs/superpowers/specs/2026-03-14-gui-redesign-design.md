# Laksefisk GUI Redesign — Design Spec

**Date:** 2026-03-14
**Tasks:** #5 (customizable GUI), #13 (better visual theme)
**Status:** Approved

## Overview

Replace the current white/light-blue horizontal GUI (1250×230px, fixed top-left) with a modern dark-themed, dockable, resizable window using **Layout H: Stacked Minimal** (vertical) that auto-reflows to **Layout F: Wide Horizontal** when docked to the top edge.

## Theme

| Token | Hex | Usage |
|-------|-----|-------|
| `BG_DARK` | `#1a1a2e` | Window & panel background |
| `PANEL_BG` | `#16213e` | Cards, sections |
| `PANEL_DEEP` | `#0f3460` | Bars, inactive elements |
| `ACCENT` | `#00d4aa` | Status, active states, fish header |
| `ALERT` | `#e94560` | Stop button, warnings, amplitude spike |
| `TEXT_PRIMARY` | `#cccccc` | Main text |
| `TEXT_DIM` | `#555555` | Secondary text, timestamps |

Font: system monospace. Panels use flat edges (tkinter doesn't support border-radius natively; no workaround needed — the dark theme looks clean with sharp corners).

## Layout Modes

### Vertical Mode (Left/Right Dock)

Default ~200px wide, resizable. Stacked top to bottom:

1. **Status bar** — Single toggle button: teal circle with ▶ when idle, solid red circle with ■ when running (static colour, no animation). Click toggles start/stop. + "Idle"/"Running" text + addon dot (teal=connected, grey=disconnected) + Cal button + gear icon
2. **Bobber view** — Zoomed crop of the watched/scan area centred on bobber. Amplitude chart overlaid at bottom with gradient fade, max 20 seconds of data. Semi-transparent bars.
3. **Fish list** — Header "Fish Caught (N)" with reset button. At least 4 items visible without scrolling. Each row: coloured bar + name + count. Resizable panel height.
4. **Log** — Collapsible (chevron toggle). Timestamped entries, newest on top. Colour-coded: teal for loot, red for warnings. Resizable panel height.

### Horizontal Mode (Top Dock)

Reflows to single row when docked top, ~110px tall:

- **Left:** Status controls + bobber view with amplitude overlay
- **Centre:** Fish list (4+ visible)
- **Right:** Log

Same content, horizontal arrangement. Panels separated by draggable sashes.

## Docking

Two mechanisms:

1. **Drag-to-snap:** Drag window to screen edge (left/top/right) → snaps to edge and switches layout mode. Drag away → floating.
2. **Settings dropdown:** Dock position selector (Left / Top / Right / Floating) in settings popup.

Implementation: detect window position on `<Configure>` event. If window x ≤ snap threshold → left dock. If y ≤ threshold → top dock. If x + width ≥ screen width - threshold → right dock. Otherwise floating (uses last layout mode or vertical default).

Snap threshold: 20px.

## Resizing

### Window
- Resizable in all directions via standard tkinter resize
- Minimum size: 160×300 (vertical), 400×90 (horizontal)
- Remembers size per dock position in config

### Internal Panels
- Panels separated by `ttk.PanedWindow` sashes (draggable dividers)
- Vertical mode: bobber view / fish list / log heights adjustable
- Horizontal mode: bobber / fish / log widths adjustable
- Minimum panel sizes: 50px
- Sash positions saved to config

## Components

### Status Bar
- **Play/stop toggle:** Single 20px canvas-drawn circle. Idle: teal background + ▶ icon. Running: red background + ■ icon. Click toggles between start/stop. Static colours, no animation.
- **Status text:** "Idle" (teal) / "Running" (teal) / "Paused" (yellow)
- **Addon dot:** Small circle, teal when pixel bridge connected, grey when not. Tooltip: "Addon: Connected" / "Addon: Not found"
- **Cal button:** Small button "Cal" with `PANEL_DEEP` background. Click → run `sweep_calibrate()` in a thread (same as current toolbar Calibrate button). Tooltip shows current mult/closeness values. The "Auto-calibrate" checkbox in settings controls whether calibration runs automatically on first cast.
- **Gear icon:** Opens settings popup (toplevel window)

### Bobber View
- Shows only the `WowScreen` capture region, cropped and zoomed to centre around detected bobber position
- **Zoom logic:** Crop happens on the raw PIL bitmap before display. When bobber is found, calculate a crop rectangle (~3x zoom) centred on `event.point` in bitmap coordinates. Clamp to bitmap bounds. Resize the crop to fill the canvas. When no bobber found: show full scan area (current behaviour). No interpolation/smoothing — hard snap to new position each frame.
- Reticle overlay on bobber position (existing `draw_reticle`, applied after crop)
- **Amplitude overlay:** Bottom 20% of bobber view canvas. Gradient from transparent to semi-opaque black (`BG_DARK` at 80% opacity). Vertical bars drawn on canvas. Each bar = one amplitude sample. Y-axis range: -15 to 10 (same as current `BobberChart`). Strike threshold line at -7 (dashed). Max 20 seconds shown (vs current 25s). Spike bar (exceeds strike) uses `ALERT` colour, normal bars use `PANEL_DEEP` at 60% opacity. Data still collected via existing `BobberChart.add()` logic, just rendered differently.
- **FlyingFishOverlay:** Attaches to the bobber view canvas (same canvas as amplitude overlay). Z-order: bobber image → amplitude bars → flying fish on top.

### Fish List
- Header row: "Fish Caught (N)" in `ACCENT` + reset icon (↻)
- Each row: horizontal bar (filled blocks or drawn rectangle in `PANEL_DEEP`) proportional to percentage + fish name + "xN" count
- Minimum 4 rows visible before scrolling
- Scrollable if more than visible area allows
- Background: `PANEL_BG`

### Log Panel
- Header row: "Log" + collapse chevron (▼/▲)
- Monospace text, newest entry on top
- Max 200 entries
- Colour coding: timestamp in `TEXT_DIM`, normal text in `TEXT_PRIMARY`, loot names in `ACCENT`, warnings in `ALERT`
- Collapsible: chevron toggles between full height and single-line (just header)
- Background: `PANEL_BG`

### Settings Popup
Toplevel window opened via gear icon. Dark themed to match. Contains:

- **Cast key** — key selector (current hex input)
- **Lure key** — key selector + None option
- **Loot wait** — min/max sliders (0.0–10.0s, matching current range)
- **Colour mode** — Red/Blue radio buttons
- **Colour multiplier** — slider (0–3.0)
- **Colour closeness** — slider (0–5.0)
- **Auto-calibrate** — checkbox
- **Stop on player nearby** — checkbox (moved from toolbar; popup-only, not on status bar)
- **Stop on bags full** — checkbox (moved from toolbar; popup-only, not on status bar)
- **Dock position** — dropdown (Left / Top / Right / Floating)
- **Always on top** — checkbox (default: on)
- **Reset to defaults** button

The existing `ColourConfigWindow` content (capture preview, colour map) moves into a tab or expandable section within this unified settings popup.

## Config Persistence

All new settings saved to `config.json`:

```json
{
  "dock_position": "right",
  "window_width": 200,
  "window_height": 500,
  "horizontal_height": 110,
  "vertical_sash_positions": [120, 280],
  "horizontal_sash_positions": [130, 350],
  "log_collapsed": false,
  "bobber_zoom": 3.0,
  "always_on_top": true
}
```

Merged with existing config keys (cast_key, lure_key, etc.).

**Save triggers:** Config is written on window close (`WM_DELETE_WINDOW`), dock position change, and log collapse toggle. NOT on every resize/sash drag (too frequent). Sash positions and window size are captured at save time from current widget state.

## Migration from Current GUI

### What stays
- `BobberChart` logic (data collection, amplitude tracking) — repurposed as overlay renderer
- `FlyingFishOverlay` — keep the celebration animation, attach to bobber view canvas
- `ColourConfigWindow` content — moved into settings popup
- `FishTracker` integration — same data, new rendering
- `PixelBridge` / addon status detection
- Bot thread management, queue-based logging
- `draw_reticle` function
- **mss DPI warm-up:** The `with mss.mss(): pass` call at the top of `App.__init__` MUST be preserved before any tkinter geometry calls (mss changes Windows DPI awareness on first use, corrupting geometry if called later)
- **Always-on-top:** Retained by default (`-topmost` attribute), with new `always_on_top` config key to make it toggleable in settings

### What changes
- `App` class rewritten with new layout system
- `BobberChart` canvas widget → amplitude drawn directly on bobber view canvas as overlay
- Colour scheme: all white/light-blue constants replaced with dark theme tokens
- Window positioning: fixed top-left → dockable with snap detection
- Fish list: text widget → canvas or frame-based rendering for bar charts
- Log: same text widget, new colours
- Settings: separate `ColourConfigWindow` → unified settings popup

### What's removed
- Fixed 1250×230 geometry
- White/light-blue colour constants
- Hardcoded top-left position

## File Changes

- **`gui.py`** — Major rewrite of `App` class, `BobberChart` refactored, `ColourConfigWindow` merged into settings popup, new theme constants
- **`config.json`** — New keys for dock position, window sizes, sash positions

No other files change. The bot, bobber finder, pixel bridge, fish tracker, and all other modules are unaffected.

## Out of Scope

- Task #8 (save all settings) — partially addressed by config persistence, full implementation is separate
- Task #10 (adjustable bite sensitivity) — can be added to settings popup later
- Mobile/responsive scaling
- Multiple monitor support (uses primary monitor only)
