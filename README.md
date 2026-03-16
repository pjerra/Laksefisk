# Laksefisk

A World of Warcraft fishing bot for Windows. Python port of [FishingFun](https://github.com/julianperrott/FishingFun) by Julian Perrott.

Detects the fishing bobber on screen using pixel colour analysis, watches for the bite (bobber dip), then moves the mouse to the bobber with human-like movement and right-clicks to loot.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Windows](https://img.shields.io/badge/Platform-Windows-lightgrey) ![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **Bobber detection** — Scans screen for red (or blue) bobber feather using configurable colour thresholds
- **Bobber stabilization** — EMA smoothing on Y-axis with locked X to prevent jitter from frame-to-frame noise
- **Bite detection** — Tracks bobber Y-position median and triggers on downward dip
- **Human-like mouse movement** — Cubic Bezier curves with random control points, smoothstep easing, and pixel jitter
- **Random click offset** — Loot clicks land within ±5px of bobber center to avoid detectable patterns
- **Pixel bridge** — WoW addon communicates game state (loot, bobber status, fishing state) to the bot via coloured pixels — no memory reading or chat log parsing
- **Auto container opening** — Automatically opens clam/lockbox containers after looting
- **Auto junk deletion** — Detects and deletes junk items flagged by the addon
- **Lure macro support** — Automatically re-applies lure every 10 min 10 sec
- **Configurable loot delay** — Random wait before looting (min–max range)
- **Fish tracker** — Counts and displays caught fish with percentages, powered by the pixel bridge
- **Loot report** — Generates an interactive HTML report with all-time totals and per-session breakdowns
- **Bobber calibration** — Auto-tunes colour thresholds for your screen/environment
- **GUI** — Dark-themed tkinter interface with live screenshot, bobber movement chart, and log panel
- **Modal settings** — Settings popup stays above the main window and blocks interaction until closed
- **Always-on-top** — GUI sits in the top screen strip, outside WoW's capture zone
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
- **mss** — Fast screen capture
- **psutil** — WoW process detection
- **pywin32** — Windows API (keyboard/mouse input)

### WoW Addon

The bot communicates with the game through the **Laksefisk addon**, which encodes game events as coloured pixels on screen.

1. Copy the `addon/` folder contents to your WoW AddOns directory:
   ```
   World of Warcraft/_anniversary_/Interface/AddOns/Laksefisk/
   ```
   The folder should contain `Laksefisk.lua` and `Laksefisk.toc`.

2. Enable the addon in WoW's addon menu and `/reload` if needed.

3. The addon renders a small pixel strip in the top-left corner of the screen. The bot reads these pixels to detect:
   - What item was looted (item ID)
   - Whether the bobber is active
   - Whether junk is on the cursor (for auto-delete)
   - Current fishing state

## Usage

### GUI (recommended)

```bash
python gui.py
```

The GUI provides:

- **Cast Key** — Set the keybind for casting (virtual key code, e.g. `0x34` for key `4`)
- **Lure Key** — Optional lure macro keybind (auto-applied every 10m10s)
- **Loot Wait** — Min/max seconds to wait before looting
- **Colour Settings** — Adjust bobber colour detection thresholds
- **Auto Junk Delete** — Toggle automatic deletion of junk items
- **Live Screenshot** — Shows what the bot sees with detected pixels highlighted
- **Bobber Chart** — Real-time bobber movement with strike threshold line
- **Fish Tracker** — Live count of caught fish with item names and percentages
- **Addon Status** — Shows whether the pixel bridge is connected and reading data

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

1. **Cast** — Sends the cast key to the WoW window
2. **Search** — Captures the center of the screen and scans for red/blue pixels matching the bobber feather
3. **Stabilize** — Locks the X-axis and applies EMA smoothing to Y to filter out noise
4. **Watch** — Tracks the bobber's Y-position over time, building a median baseline
5. **Detect bite** — When the bobber dips below the median by the strike threshold, a bite is detected
6. **Loot** — Waits a random delay, moves the mouse along a curved Bezier path to the bobber (with ±5px random offset), and right-clicks
7. **Read loot** — The pixel bridge reads what item was looted from the addon's pixel encoding
8. **Post-loot** — Opens containers (clams, lockboxes) and deletes junk items if enabled

### Pixel Bridge

The addon encodes data as a row of 20 pixels using binary 0/255 values:

- Pixels 1–16: item ID in binary
- Pixels 17–20: flags (bobber active, fishing state, junk on cursor, etc.)

The Python `pixel_bridge.py` module reads these pixels via screen capture and decodes the game state without any memory reading or injection.

### Screen Capture Zone

The bot captures the center half of the screen:
- X: `screen_width/4` to `3*screen_width/4`
- Y: `screen_height/4` to `3*screen_height/4 - 100`

The GUI sits in the top quarter of the screen, safely outside this zone.

## Virtual Key Codes

Common keys for WoW keybinds:

| Key | Code | Key | Code |
|---|---|---|---|
| 1 | `0x31` | 6 | `0x36` |
| 2 | `0x32` | 7 | `0x37` |
| 3 | `0x33` | 8 | `0x38` |
| 4 | `0x34` | 9 | `0x39` |
| 5 | `0x35` | 0 | `0x30` |

Full list: [Microsoft Virtual Key Codes](https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes)

## Project Structure

```
├── gui.py                  # tkinter GUI application
├── main.py                 # Console entry point
├── fishing_bot.py          # Core bot loop (cast → find → watch → loot)
├── bobber_finder.py        # Bobber detection with EMA stabilization
├── bite_watcher.py         # Bite detection via Y-position tracking
├── pixel_bridge.py         # Reads game state from addon pixel encoding
├── fish_tracker.py         # Fish catch stats (via pixel bridge)
├── pixel_classifier.py     # Red/blue pixel colour matching
├── bobber_calibration.py   # Auto-tune bobber colour thresholds
├── loot_report.py          # Generate interactive HTML loot report
├── wow_screen.py           # Screen capture (mss)
├── wow_process.py          # Win32 API (key press, mouse movement)
├── models.py               # Data classes and enums
├── timed_action.py         # Timer utility
├── build.bat               # PyInstaller build script
├── requirements.txt        # Python dependencies
├── addon/
│   ├── Laksefisk.lua       # WoW addon — pixel bridge encoder
│   └── Laksefisk.toc       # Addon manifest
└── tests/                  # Test suite
```

## Credits

Based on [FishingFun](https://github.com/julianperrott/FishingFun) by Julian Perrott (C#/WPF). Ported to Python.

## Disclaimer

This software is provided for educational purposes. Use at your own risk. Botting may violate the World of Warcraft Terms of Service.
