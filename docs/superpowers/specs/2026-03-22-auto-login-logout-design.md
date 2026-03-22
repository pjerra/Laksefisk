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

**Note:** Exact RGB values for each sample point must be measured from actual TBC Anniversary screenshots during implementation. The implementer should capture screenshots at the character select screen and record the RGB values at each relative position. These become constants in the module.

### Loading Screen

During transitions (login and logout), WoW shows a loading screen. During this time, pixel bridge fails, the window exists, but colours don't match character select — this maps to the `unknown` state. This is expected and not an error. The login/logout poll loops treat `unknown` as "still transitioning" and continue waiting.

### Polling

Check state every 1-2 seconds in a loop until the target state is reached, with a configurable timeout.

## Login: Character Select to In-World

**Signature:** `login(slot: int = 1, timeout: int = 60) -> bool`

### Flow

1. Verify WoW window exists — fail if not
2. Detect current state — if already in-world, return `True`
3. Wait up to 10s for character select screen to appear
4. Bring WoW window to foreground (`SetForegroundWindow`) — required for hardware-level mouse input
5. Click character slot at relative position:
   - X: ~50% of window width (character list is centred)
   - Y: calculated from slot number — list starts ~35% Y, each slot spaced ~5% apart (to be validated from screenshots)
   - Random offset ±3px for human-like behaviour
   - Convert relative window position to absolute screen coordinates using `WowScreen` window position + client area offset
6. Random delay 300-800ms
7. Click "Enter World" button at ~50% X, ~91% Y (with ±3px offset, same coordinate conversion)
8. Random delay 500-1000ms
9. Poll pixel bridge until it reads successfully (= in-world), up to remaining timeout. The `unknown` state (loading screen) is expected during this phase.
10. Additional 2s settle delay for addon initialization
11. Return `True` on success, `False` on timeout

### Retry Logic

If character select is still detected 5s after clicking "Enter World" (click may have missed or WoW wasn't focused), retry the click sequence once. If still on character select after the retry, return `False` on timeout.

### Edge Cases

- **Default slot (1):** Last-played character is already selected. Clicking slot 1 is harmless and ensures correct selection.
- **Loading screen:** Can take 5-30s between click and in-world. The pixel bridge poll loop handles this naturally. The `unknown` state during loading is expected, not an error.
- **Wrong slot click:** "Enter World" enters whatever is currently selected. Acceptable risk — slot positions are reliable at relative coordinates.
- **Window not focused:** The module brings WoW to foreground before clicking. If another application steals focus during the sequence, the retry logic handles it.

## Logout: In-World to Character Select

**Signature:** `logout(timeout: int = 30) -> bool`

### Flow

1. Verify in-world via pixel bridge — fail if not
2. Bring WoW window to foreground (required for key input)
3. Press Enter to open chat
4. Random delay 100-300ms
5. Send `/logout` as a sequence of individual key presses, followed by Enter
6. Poll until pixel bridge stops reading (= left world). The `unknown` state (loading screen) is expected during transition.
7. Poll until character select screen detected (colour sampling)
8. Return `True` on success, `False` on timeout

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
- `wow_process` — mouse clicks (`left_click_at` for screen-coordinate clicks), key presses (`press_key` for individual keys). Note: `/logout` is sent as individual `press_key` calls for each character — no `type_text` function exists, so one must be added or the sequence done inline.

### Integration Points

- No GUI changes in this task. This is a foundation module only.
- Task #27 (random breaks) and #46 (auto-reconnect) will add GUI controls that use this module.
- The bot's existing disconnect detection (`_dc_count >= 5`) remains unchanged — callers will coordinate between disconnect detection and auto-reconnect.

## Config

Add `character_slot` to `constants.py` defaults:

- Key: `character_slot`
- Default: `1`
- Range: 1-10 (first visible page of characters only — scrolling not supported)
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
