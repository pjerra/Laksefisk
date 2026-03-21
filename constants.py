"""
Laksefisk constants — config defaults, colour theme, config I/O.
"""

from __future__ import annotations

import json
import os

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_SCRIPT_DIR, "config.json")
LOOT_FILE = os.path.join(_SCRIPT_DIR, "loot.json")
STRIKE_VALUE = 7

DEFAULT_CONFIG = {
    "cast_key": 0x34,
    "lure_key": None,
    "loot_wait_min": 0.5,
    "loot_wait_max": 2.0,
    "colour_mode": "Red",
    "colour_multiplier": 0.5,
    "colour_closeness_multiplier": 2.0,
    "window_width": 200,
    "window_height": 500,
    "sash_positions": [120, 280],
    "log_collapsed": False,
    "bobber_zoom": 3.0,
    "always_on_top": True,
    "stop_on_friendly": False,
    "stop_on_enemy": False,
    "stop_on_bags": False,
    "auto_delete_junk": False,
    "auto_calibrate": False,
    "bite_sensitivity": 7,
    "sound_alerts": False,
    "debug_screenshots": False,
    "pixel_bar_region": None,
    "compact_mode": False,
}

# Dark theme
BG_DARK = "#1a1a2e"
PANEL_BG = "#16213e"
PANEL_DEEP = "#0f3460"
ACCENT = "#00d4aa"
ALERT = "#e94560"
TEXT_PRIMARY = "#cccccc"
TEXT_DIM = "#555555"


def _load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            return {**DEFAULT_CONFIG, **cfg}
    except Exception:
        pass
    return dict(DEFAULT_CONFIG)


def _save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass
