# Laksefisk

A World of Warcraft fishing bot for Windows. Inspired by [FishingFun](https://github.com/julianperrott/FishingFun) by Julian Perrott.

Detects the fishing bobber on screen using pixel colour analysis, watches for the bite (bobber dip), then moves the mouse to the bobber with human-like movement and right-clicks to loot.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Windows](https://img.shields.io/badge/Platform-Windows-lightgrey) ![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **Bobber detection** — Scans screen for red (or blue) bobber feather using configurable colour thresholds
- **Bobber stabilization** — EMA smoothing on Y-axis with locked X to prevent jitter from frame-to-frame noise
- **Bite detection** — Tracks bobber Y-position median and triggers on downward dip
- **Human-like mouse movement** — Cubic Bezier curves with random control points, smoothstep easing, and pixel jitter
- **Random click offset** — Loot clicks land within ±5px of bobber center to avoid detectable patterns
- **WoW-only window capture** — Captures WoW via PrintWindow (DirectX content), works even with overlapping windows
- **Pixel bridge** — WoW addon communicates game state (loot, HP, combat, nearby players) to the bot via coloured pixels — no memory reading or chat log parsing
- **Addon settings GUI** — In-game settings panel to configure bot settings from within WoW, synced via pixel bridge
- **Auto container opening** — Automatically opens clam/lockbox containers after looting
- **Auto junk deletion** — Detects and deletes junk items flagged by the addon's delete list
- **Lure macro support** — Automatically re-applies lure every 10 min 10 sec
- **Configurable loot delay** — Random wait before looting (min–max range)
- **Auto-calibration** — Multi-frame bobber colour calibration at session start, picks thresholds with lowest variance
- **Fish tracker** — Counts and displays caught fish with percentages, powered by the pixel bridge
- **Loot report** — Generates an interactive HTML report with all-time totals and per-session breakdowns
- **Player detection** — Detects nearby friendly and enemy players via addon nameplates API, can pause fishing
- **Sound alerts** — Audio notifications for whispers, nearby players, bags full, and bot stopped
- **Emergency stop** — Automatically stops on death, combat, or disconnect (5 consecutive bridge failures)
- **Debug screenshots** — Saves screenshots when bobber detection fails for troubleshooting
- **GUI tooltips** — Hover tooltips on all controls explaining what each one does
- **GUI** — Dark-themed tkinter interface with live screenshot, bobber movement chart, and log panel
- **Modal settings** — Settings popup with colour preview, detection tuning, and feature toggles
- **Always-on-top** — GUI sits above other windows, outside WoW's capture zone
- **Standalone exe** — Build a single-file `.exe` with the included build script

## Requirements

- Windows 10/11
- Python 3.10+
- World of Warcraft running in windowed or borderless windowed mode

## Installation

```bash
git clone https://github.com/pjerra/Laksefisk.git
cd Laksefisk
pip install -r requirements.txt
```

### Dependencies

- **Pillow** — Image processing
- **psutil** — WoW process detection
- **pywin32** — Windows API (keyboard/mouse input, window capture)

### WoW Addon

The bot communicates with the game through the **Laksefisk addon**, which encodes game events as coloured pixels on screen.

1. Copy the `addon/Laksefisk` folder to your WoW AddOns directory:
   ```
   World of Warcraft/_anniversary_/Interface/AddOns/Laksefisk/
   ```
   The folder should contain `Laksefisk.lua` and `Laksefisk.toc`.

2. Enable the addon in WoW's addon menu and `/reload` if needed.

3. The addon renders a pixel strip at the bottom of the screen. The bot reads these pixels to detect:
   - What item was looted (item ID)
   - Fishing state, combat, alive/dead, HP
   - Nearby players (friendly and enemy)
   - Whether junk is on the cursor (for auto-delete)
   - Bait timer remaining
   - Whisper/say/yell chat events

### Addon Commands

| Command | Description |
|---|---|
| `/lf show` / `/lf hide` | Show/hide the pixel bar |
| `/lf status` | Toggle status bar |
| `/lf settings` | Toggle in-game settings panel |
| `/lf settingsbar` | Toggle settings pixel bar (row 2) |
| `/lf move` | Unlock/lock pixel bar for dragging |
| `/lf resetbar` | Reset pixel bar to default position |
| `/lf delete add/remove/list/clear` | Manage junk delete list |
| `/lf containers` | Toggle auto-open containers |
| `/lf open` | Open all containers in bags |
| `/lf nearby` | Toggle nearby player detection |

## Usage

### GUI (recommended)

```bash
python gui.py
```

The GUI provides:

- **Cast Key** — Set the keybind for casting
- **Lure Key** — Optional lure macro keybind (auto-applied every 10m10s)
- **Loot Wait** — Min/max seconds to wait before looting
- **Bite Sensitivity** — How strong a bobber dip must be to count as a bite
- **Colour Settings** — Adjust bobber colour detection thresholds with live preview
- **Stop Conditions** — Stop on friendly/enemy player, bags full
- **Auto Junk Delete** — Toggle automatic deletion of junk items
- **Sound Alerts** — Audio notifications for events
- **Live Screenshot** — Shows what the bot sees with detected pixels highlighted
- **Bobber Chart** — Real-time bobber movement with amplitude overlay
- **Fish Tracker** — Live count of caught fish (click to open HTML report)
- **Addon Status** — Shows whether the pixel bridge is connected

### Console

```bash
python main.py [options]
```

| Option | Default | Description |
|---|---|---|
| `--cast-key` | `0x34` (key 4) | Virtual key code for cast |
| `--lure-key` | None | Virtual key code for lure macro |
| `--loot-min` | `0.5` | Min loot delay (seconds) |
| `--loot-max` | `2.0` | Max loot delay (seconds) |
| `--blue` | off | Use blue bobber mode |
| `--strike` | `7` | Bite detection threshold |

### Bobber Calibration

Run the calibration tool to auto-tune colour thresholds for your screen:

```bash
python bobber_calibration.py
```

Cast your line, then the tool captures the screen and sweeps threshold values to find the tightest settings that reliably detect the bobber.

### Loot Report

Generate an interactive HTML report of your fishing history:

```bash
python loot_report.py
```

Opens `loot.html` with all-time totals and per-session breakdowns.

### Building a Standalone Exe

```bash
build.bat
```

Produces `Laksefisk.exe` via PyInstaller.

## How It Works

1. **Cast** — Sends the cast key to the WoW window via PostMessage
2. **Search** — Captures the center of the WoW window and scans for red/blue pixels matching the bobber feather
3. **Stabilize** — Locks the X-axis and applies EMA smoothing to Y to filter out noise
4. **Watch** — Tracks the bobber's Y-position over time, building a median baseline
5. **Detect bite** — When the bobber dips below the median by the strike threshold, a bite is detected
6. **Loot** — Waits a random delay, moves the mouse along a curved Bezier path to the bobber (with ±5px random offset), and right-clicks
7. **Read loot** — The pixel bridge reads what item was looted from the addon's pixel encoding
8. **Post-loot** — Opens containers (clams, lockboxes) and deletes junk items if enabled

### Pixel Bridge

The addon encodes data as a row of 21 pixels using binary 0/255 values:

- Pixels 0–1: Marker and status flags (alive, combat, fishing)
- Pixels 2–7: Loot counter, bags full, cast parity, catch count, player nearby, chat flags
- Pixels 8–13: Item ID (6 pixels × 3 channels = 18 bits)
- Pixels 14–16: Bait timer (9 bits)
- Pixels 17–19: HP percent (8 bits) + junk on cursor flag
- Pixel 20: Enemy nearby flag

An optional second row encodes bot settings (stop conditions, keys, thresholds) for the addon settings GUI.

The Python `pixel_bridge.py` module reads these pixels via window capture and decodes the game state without any memory reading or injection.

## Project Structure

```
├── gui.py                  # tkinter GUI application
├── main.py                 # Console entry point
├── fishing_bot.py          # Core bot loop (cast → find → watch → loot)
├── bobber_finder.py        # Bobber detection with EMA stabilization
├── bite_watcher.py         # Bite detection via Y-position tracking
├── pixel_bridge.py         # Reads game state from addon pixel encoding
├── pixel_classifier.py     # Red/blue pixel colour matching
├── fish_tracker.py         # Fish catch stats (via pixel bridge)
├── wow_screen.py           # WoW window capture (PrintWindow)
├── wow_process.py          # Win32 API (key press, mouse movement)
├── wow_login.py            # Auto login/logout (character select detection)
├── constants.py            # Default config and theme colours
├── widgets.py              # Custom tkinter widgets (sliders, tooltips)
├── settings.py             # Settings popup window
├── bobber_calibration.py   # Auto-tune bobber colour thresholds
├── loot_report.py          # Generate interactive HTML loot report
├── item_lookup.json        # Item ID → name mapping for pixel bridge
├── models.py               # Data classes and enums
├── timed_action.py         # Timer utility
├── build.bat               # PyInstaller build script
├── requirements.txt        # Python dependencies
├── addon/
│   └── Laksefisk/
│       ├── Laksefisk.lua   # WoW addon — pixel bridge + settings GUI
│       └── Laksefisk.toc   # Addon manifest
└── tests/                  # Test suite
```

## Credits

Based on [FishingFun](https://github.com/julianperrott/FishingFun) by Julian Perrott (C#/WPF). Ported to Python.

## Disclaimer

This software is provided for educational purposes. Use at your own risk. Botting may violate the World of Warcraft Terms of Service.
