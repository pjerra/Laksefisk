# Laksefisk

A World of Warcraft fishing bot for Windows. Python port of [FishingFun](https://github.com/julianperrott/FishingFun) by Julian Perrott.

Detects the fishing bobber on screen using pixel colour analysis, watches for the bite (bobber dip), then moves the mouse to the bobber with human-like movement and right-clicks to loot.

![Python](https://img.shields.io/badge/Python-3.10+-blue) ![Windows](https://img.shields.io/badge/Platform-Windows-lightgrey) ![License](https://img.shields.io/badge/License-MIT-green)

## Features

- **Bobber detection** — Scans screen for red (or blue) bobber feather using configurable colour thresholds
- **Bite detection** — Tracks bobber Y-position median and triggers on downward dip
- **Human-like mouse movement** — Cubic Bezier curves with random control points, smoothstep easing, and pixel jitter
- **Lure macro support** — Automatically re-applies lure every 10 min 10 sec
- **Configurable loot delay** — Random wait before looting (min–max range)
- **Fish tracker** — Reads WoW's chat log to count and display caught fish with percentages (requires `/chatlog` in WoW)
- **GUI** — tkinter interface with live screenshot, bobber movement chart, and log panel
- **Always-on-top** — GUI sits in the top screen strip, outside WoW's capture zone
- **WoW Classic support** — Adjusted colour thresholds for Classic client

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
- **Live Screenshot** — Shows what the bot sees with detected pixels highlighted
- **Bobber Chart** — Real-time bobber movement with strike threshold line

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

## How It Works

1. **Cast** — Sends the cast key to the WoW window
2. **Search** — Captures the center of the screen and scans for red/blue pixels matching the bobber feather
3. **Watch** — Tracks the bobber's Y-position over time, building a median baseline
4. **Detect bite** — When the bobber dips below the median by the strike threshold, a bite is detected
5. **Loot** — Waits a random delay, moves the mouse along a curved Bezier path to the bobber, and right-clicks

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
├── gui.py               # tkinter GUI application
├── main.py              # Console entry point
├── fishing_bot.py       # Core bot loop (cast → find → watch → loot)
├── bobber_finder.py     # Bobber detection via pixel scanning
├── bite_watcher.py      # Bite detection via Y-position tracking
├── fish_tracker.py      # Chat log parser for fish catch stats
├── pixel_classifier.py  # Red/blue pixel colour matching
├── wow_screen.py        # Screen capture (mss)
├── wow_process.py       # Win32 API (key press, mouse movement)
├── models.py            # Data classes and enums
├── timed_action.py      # Timer utility
└── requirements.txt     # Python dependencies
```

## Credits

Based on [FishingFun](https://github.com/julianperrott/FishingFun) by Julian Perrott (C#/WPF). Ported to Python.

## Disclaimer

This software is provided for educational purposes. Use at your own risk. Botting may violate the World of Warcraft Terms of Service.
