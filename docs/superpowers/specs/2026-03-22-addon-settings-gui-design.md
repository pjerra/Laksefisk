# Addon Settings GUI — Design Spec

**Task:** #57 — In-game WoW addon GUI for viewing bot status and changing settings
**Date:** 2026-03-22

## Overview

Add an in-game GUI to the Laksefisk WoW addon with two components: a compact always-visible status bar and a full tabbed settings panel. Add a second row of 13 pixels below the existing pixel bar to encode settings. The bot auto-detects addon version by checking for a version marker pixel below row 1.

## Goals

1. View bot status (fishing state, catches, bags, alerts) without alt-tabbing
2. Change bot settings from inside WoW
3. Manage delete list, whitelist, and skip filters from a GUI instead of slash commands
4. Backward compatible — old addon still works, bot falls back to local config

## Pixel Bar — Two-Row Layout

The pixel bar becomes a 2-row grid. Row 1 (21 pixels) is unchanged. Row 2 (13 settings pixels + 8 empty for future) sits directly below row 1. Same width (105px at 5×5 blocks), just 5px taller. All multi-bit values in row 2 are encoded MSB-first, consistent with row 1.

**Encoding reminder:** Each RGB channel = exactly 1 bit (0 or 255). A "4-bit value" uses 4 channels across multiple pixels. All encoding is binary, immune to gamma correction.

### Row 1: Status (pixels 0-20, unchanged)

| Pixel | R | G | B |
|-------|---|---|---|
| [0] | Sync magenta (255,0,255) |||
| [1] | Sync cyan (0,255,255) |||
| [2] | alive | combat | fishing |
| [3] | loot_parity | bags_full | cast_parity |
| [4] | whisper | say | yell |
| [5-7] | catch_count (8-bit) || [7]B=player_nearby |
| [8-13] | item_id (18-bit) |||
| [14-16] | bait_seconds (8-bit) || [16]B=mouseover_bobber |
| [17-19] | hp_percent (8-bit) || [19]B=junk_on_cursor |
| [20] | — | — | enemy_nearby |

### Row 2: Settings (pixels 21-33)

| Pixel | R | G | B |
|-------|---|---|---|
| [21] | 0 (fixed) | 255 (fixed) | 0 (fixed) |
| [22] | stop_friendly | stop_enemy | stop_bags |
| [23] | auto_delete | auto_calibrate | sound_alerts |
| [24] | colour_mode (0=Red) | skip_party | skip_guild |
| [25] | skip_friends | cast_key[4] | cast_key[3] |
| [26] | cast_key[2] | cast_key[1] | cast_key[0] |
| [27] | lure_key[4] | lure_key[3] | lure_key[2] |
| [28] | lure_key[1] | lure_key[0] | wait_min[3] |
| [29] | wait_min[2] | wait_min[1] | wait_min[0] |
| [30] | wait_max[3] | wait_max[2] | wait_max[1] |
| [31] | wait_max[0] | col_mult[3] | col_mult[2] |
| [32] | col_mult[1] | col_mult[0] | col_close[3] |
| [33] | col_close[2] | col_close[1] | col_close[0] |

Pixels 34-41 (row 2, columns 14-21) are empty — reserved for future expansion.

**Pixel [21] — Version marker:** Always green (0, 255, 0). Unambiguously identifies v2 addon. The bot checks one block-height below pixel [0] for this marker.

### Bit budget

| Data | Bits | Notes |
|------|------|-------|
| Version marker | 3 (fixed) | Pixel 21 = green |
| Booleans (10) | 10 | stop_friendly, stop_enemy, stop_bags, auto_delete, auto_calibrate, sound_alerts, colour_mode, skip_party, skip_guild, skip_friends |
| Cast key (5-bit index) | 5 | Lookup table, 32 common keys |
| Lure key (5-bit index) | 5 | 0 = none |
| Loot wait min (4-bit) | 4 | 0-15 → 0.0-3.0s, step 0.2s |
| Loot wait max (4-bit) | 4 | 0-15 → 0.0-3.0s, step 0.2s |
| Colour multiplier (4-bit) | 4 | 0-15 → 0.0-3.0, step 0.2 |
| Colour closeness (4-bit) | 4 | 0-15 → 0.0-5.0, step ~0.33 |
| **Total** | **39 bits** | **13 pixels** |

### 5-bit key index table (shared Lua + Python)

Both addon and bot use the same lookup table. Index 0 = none/unset.

| Index | Key | VK Code |
|-------|-----|---------|
| 0 | None | — |
| 1 | 1 | 0x31 |
| 2 | 2 | 0x32 |
| 3 | 3 | 0x33 |
| 4 | 4 | 0x34 |
| 5 | 5 | 0x35 |
| 6 | 6 | 0x36 |
| 7 | 7 | 0x37 |
| 8 | 8 | 0x38 |
| 9 | 9 | 0x39 |
| 10 | 0 | 0x30 |
| 11 | F1 | 0x70 |
| 12 | F2 | 0x71 |
| 13 | F3 | 0x72 |
| 14 | F4 | 0x73 |
| 15 | F5 | 0x74 |
| 16 | F6 | 0x75 |
| 17 | F7 | 0x76 |
| 18 | F8 | 0x77 |
| 19 | F9 | 0x78 |
| 20 | F10 | 0x79 |
| 21 | F11 | 0x7A |
| 22 | F12 | 0x7B |
| 23 | - | 0xBD |
| 24 | = | 0xBB |
| 25 | Num0 | 0x60 |
| 26 | Num1 | 0x61 |
| 27 | Num+ | 0x6B |
| 28 | Num- | 0x6D |
| 29 | ` | 0xC0 |
| 30 | [ | 0xDB |
| 31 | ] | 0xDD |

### 4-bit slider value mappings

| Setting | Range | Step | Formula |
|---------|-------|------|---------|
| loot_wait_min | 0.0 – 3.0s | 0.2s | value × 0.2 |
| loot_wait_max | 0.0 – 3.0s | 0.2s | value × 0.2 |
| colour_multiplier | 0.0 – 3.0 | 0.2 | value × 0.2 |
| colour_closeness_multiplier | 0.0 – 5.0 | ~0.33 | value × (5.0 / 15) |

**Rounding note:** The 0.2 step size cannot represent 0.5 exactly. Defaults that fall between steps use the nearest index: loot_wait_min default 0.5 → index 3 (0.6s), colour_multiplier default 0.5 → index 3 (0.6). This is an acceptable approximation.

### Version detection

1. Bot finds sync markers (magenta → cyan) in row 1 (same as today)
2. Read 21 pixels of row 1 (same as today)
3. Check at Y offset `bar_y + pixel_size` below pixel [0]: is the colour green (0, 255, 0)?
4. If yes → v2 addon, expand cached capture region height to `pixel_size * 2 + pad * 2`, read 13 settings pixels from row 2
5. If no → v1 addon, use local config

### Intentionally omitted from pixel encoding

These settings remain bot-only (controlled from Python GUI, not WoW addon):
- `bite_sensitivity` — fine-tuning during session is rare, and the amplitude overlay is only visible in the Python GUI
- `debug_screenshots` — developer/debug tool, not user-facing
- `compact_mode` — Python GUI layout option, not relevant in WoW
- `bobber_zoom` — Python GUI preview zoom, not relevant in WoW
- `window_width/height`, `sash_positions`, `log_collapsed` — Python GUI layout

### Lists (addon-only, no pixel encoding)

The delete list, whitelist, and skip filters are string-based data stored in SavedVariables. They are acted on by the addon directly (delete junk, filter nearby players) and do not need to flow through the pixel bridge. The bot does not need to know these lists — the addon handles the logic.

- `deleteList` — array of item names
- `whitelist` — array of player names
- `skipParty`, `skipGuild`, `skipFriends` — booleans (also encoded as pixels for bot awareness)

Note: skip_party/guild/friends are encoded in pixels (pixel 24-25) so the bot can also respect them when processing nearby player signals. The delete list and whitelist remain addon-only.

## In-Game GUI

### Component 1: Compact Status Bar

Small floating frame, always visible while fishing. Toggle with `/lf status`.

**Displays:**
- Fishing state: "Fishing" / "Idle" / "Dead" / "Combat" (no bot-specific language for anti-cheat safety)
- Fish caught this session (count)
- Last item caught (name)
- Session duration (time since first cast)
- Bag slots remaining (free/total)
- Nearby player alert indicator
- Reason stopped (if applicable: player nearby, bags full, dead, combat)

**Data source:** All derived from addon's own state — catch_count, item_id → item name lookup, bags scan, fishing channel state, player detection. Session duration = time since first UNIT_SPELLCAST_CHANNEL_START with "Fishing" spell.

**Behaviour:**
- Draggable, position saved to SavedVariables
- Click title to collapse/expand
- Updates every 0.05s (same as pixel bar refresh)

### Component 2: Settings Panel

Full settings window, opened with `/lf settings`, closed with Esc or X button.

**3 tabs:**

#### General tab
- **Stop Conditions:** checkboxes for stop_friendly, stop_enemy, stop_bags
- **Features:** checkboxes for auto_delete, auto_calibrate, sound_alerts, nearby player alerts
- **Keys:** cast key and lure key — click field, press key to capture. WoW key name → key index via lookup table
- **Timing:** loot wait min/max (sliders, 0.0-3.0s, step 0.2s)
- **Pixel Bar:** "Move Bar" button (triggers existing move/drag logic)
- **Reset Defaults** button

#### Lists tab
- **Auto-Delete List:** scrollable list of junk items, with add (text input + button), remove (X per item), clear button
- **Player Whitelist:** same pattern — scrollable list, add/remove/clear
- **Auto-Skip:** checkboxes for skip party, skip guild, skip friends

#### Detection tab
- **Colour Mode:** Red / Blue radio buttons
- **Colour Multiplier:** slider 0.0-3.0 (step 0.2)
- **Colour Closeness:** slider 0.0-5.0 (step ~0.33)

**Behaviour:**
- Draggable, position saved to SavedVariables
- Esc closes the panel
- Setting changes apply immediately to SavedVariables + pixel bar update
- Tab state remembered (which tab was last open)

### Key Capture

WoW addon API provides key names via OnKeyDown handlers. The addon captures the key name, looks it up in the shared key index table, and stores the index. If a key is not in the table, the capture is rejected (feedback: "Key not supported"). The index is written to pixels and decoded to VK code on the Python side using the same table.

### Settings Initialization

On first load with new addon (no settings in SavedVariables), initialize defaults matching `DEFAULT_CONFIG` in constants.py:
- stop_friendly = false, stop_enemy = false, stop_bags = false
- auto_delete = false, auto_calibrate = false, sound_alerts = false
- colour_mode = "Red" (index 0), skip_party = false, skip_guild = false, skip_friends = false
- cast_key = index 4 (key "4", VK 0x34), lure_key = index 0 (none)
- loot_wait_min = index 3 (0.6s, nearest to default 0.5), loot_wait_max = index 10 (2.0s)
- colour_multiplier = index 3 (0.6, nearest to default 0.5), colour_closeness_multiplier = index 6 (2.0)

## Python Bot Changes

### pixel_bridge.py

- Extend `PixelBridgeData` with settings fields: stop_friendly, stop_enemy, stop_bags, auto_delete, auto_calibrate, sound_alerts, colour_mode, skip_party, skip_guild, skip_friends, cast_key (VK int), lure_key (VK int or None), loot_wait_min (float), loot_wait_max (float), colour_multiplier (float), colour_closeness_multiplier (float)
- Add `addon_version` field (1 or 2)
- After reading row 1, check for version marker one block below
- If v2: read row 2 pixels, decode settings using key index table and slider mappings
- Add shared `KEY_INDEX_TABLE` list (index → VK code)

### fishing_bot.py

- When `addon_version == 2`: apply settings from pixel bridge data to bot state each poll cycle
- When `addon_version == 1`: use local config as before (no change)

### settings.py (Python GUI)

- No changes needed — stays fully editable
- Addon pixel values override bot state directly, independent of GUI config
- Both can change settings; addon values win on next pixel read

## Backward Compatibility

- Old addon (21 pixels, single row) continues to work — bot auto-detects by absence of version marker
- Swapping addons = replace the addon folder in WoW, no bot configuration changes
- No breaking changes to existing pixel layout (row 1 identical)
- New addon with old bot = row 2 pixels ignored (bot only reads row 1)

## Slash Commands

Existing commands unchanged. New commands:
- `/lf status` — toggle status bar visibility
- `/lf settings` — toggle settings panel visibility

## Files Changed

**Addon:**
- `Laksefisk.lua` — add row 2 pixel blocks, add settings to SavedVariables, add GUI frames (status bar + settings panel with 3 tabs), add key index lookup table, add new slash commands

**Python:**
- `pixel_bridge.py` — two-row detection, read row 2 settings pixels, key index table, slider decode
- `fishing_bot.py` — apply pixel-sourced settings when addon_version == 2
- `constants.py` — add shared KEY_INDEX_TABLE (or put in pixel_bridge.py)
