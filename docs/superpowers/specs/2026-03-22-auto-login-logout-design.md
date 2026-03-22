# Auto Login/Logout Design Spec

## Overview

New standalone module (`wow_login.py`) that automates WoW character select login and `/logout`. Foundation for task #27 (random breaks) and task #46 (auto-reconnect). Does not handle Battle.net authentication — assumes the launcher keeps you logged in.

**Target version:** WoW TBC Anniversary Classic

## Screen State Detection

The module must detect which screen WoW is showing without the addon (which only loads in-world).

### States

| State | Detection Method |
|---|---|
| `in_world` | Pixel bridge reads successfully |
| `character_select` | Pixel bridge fails + WoW window exists + known UI colours at relative positions |
| `unknown` | Pixel bridge fails + WoW window exists + colours don't match character select |
| `no_window` | `WowScreen` can't find WoW window handle |

### Character Select Detection

Sample 3-4 relative positions on the captured WoW window for known TBC Anniversary character select UI colours:

- **"Enter World" button area** — ~50% X, ~91% Y. Distinct button colour against dark background.
- **Character list background** — ~25% X, ~50% Y. Dark panel colour.
- **Bottom bar** — ~50% X, ~95% Y. Characteristic UI frame colour.

Use colour tolerance of ±20 per channel to handle rendering differences. All positions are relative to window dimensions, making detection resolution-independent.

### Polling

Check state every 1-2 seconds in a loop until the target state is reached, with a configurable timeout.

## Login: Character Select to In-World

**Signature:** `login(slot: int = 1, timeout: int = 60) -> bool`

### Flow

1. Verify WoW window exists — fail if not
2. Detect current state — if already in-world, return `True`
3. Wait up to 10s for character select screen to appear
4. Click character slot at relative position:
   - X: ~50% of window width (character list is centred)
   - Y: calculated from slot number — list starts ~35% Y, each slot spaced ~5% apart
   - Random offset ±3px for human-like behaviour
5. Random delay 300-800ms
6. Click "Enter World" button at ~50% X, ~91% Y (with ±3px offset)
7. Random delay 500-1000ms
8. Poll pixel bridge until it reads successfully (= in-world), up to remaining timeout
9. Additional 2s settle delay for addon initialization
10. Return `True` on success, `False` on timeout

### Edge Cases

- **Default slot (1):** Last-played character is already selected. Clicking slot 1 is harmless and ensures correct selection.
- **Loading screen:** Can take 5-30s between click and in-world. The pixel bridge poll loop handles this naturally.
- **Wrong slot click:** "Enter World" enters whatever is currently selected. Acceptable risk — slot positions are reliable at relative coordinates.

## Logout: In-World to Character Select

**Signature:** `logout(timeout: int = 30) -> bool`

### Flow

1. Verify in-world via pixel bridge — fail if not
2. Press Enter to open chat
3. Random delay 100-300ms
4. Type `/logout` followed by Enter
5. Poll until pixel bridge stops reading (= left world)
6. Poll until character select screen detected (colour sampling)
7. Return `True` on success, `False` on timeout

### Timing

- In inns/cities: instant logout
- In unsafe areas: 20-second logout cast (TBC), interruptible by movement or damage
- Default timeout of 30s covers the worst case

### Edge Cases

- **In combat:** `/logout` fails. Caller should check combat state via pixel bridge before calling.
- **Logout interrupted:** Damage or movement cancels the cast. Detected because pixel bridge keeps reading (still in-world). Returns `False` on timeout.
- **Chat already open:** `/logout` starts with `/`, so typing it works regardless of chat state.

## Module Structure

### New File: `wow_login.py`

```python
class WowLogin:
    def __init__(self, wow_screen: WowScreen, pixel_bridge: PixelBridge):
        ...

    def detect_state(self) -> str:
        """Returns: 'in_world', 'character_select', 'unknown', 'no_window'"""

    def login(self, slot: int = 1, timeout: int = 60) -> bool:
        """Character select -> in-world. Returns True on success."""

    def logout(self, timeout: int = 30) -> bool:
        """In-world -> character select. Returns True on success."""
```

### Dependencies

- `WowScreen` — window capture and existence check
- `PixelBridge` — in-world detection (bridge read success = in-world)
- `wow_process` — mouse clicks (`click_at`), key presses (`press_key`, `type_text`)

### Integration Points

- No GUI changes in this task. This is a foundation module only.
- Task #27 (random breaks) and #46 (auto-reconnect) will add GUI controls that use this module.
- The bot's existing disconnect detection (`_dc_count >= 5`) remains unchanged — callers will coordinate between disconnect detection and auto-reconnect.

## Config

Add `character_slot` to `constants.py` defaults:

- Key: `character_slot`
- Default: `1`
- Range: 1-10
- Stored in config file via existing config system

## Logging

Uses existing `logger` pattern. Logs:

- State transitions (`detect_state` results)
- Click positions and random offsets
- Login/logout success or timeout with elapsed time
- Errors (no window, unexpected state)

## Out of Scope

- Battle.net authentication (handled by launcher)
- GUI controls (added by tasks #27 and #46)
- Automatic fishing resume after login (caller's responsibility)
- Realm selection (assumes correct realm is already selected)
- Queue handling (if there's a login queue, module returns `False` on timeout)
