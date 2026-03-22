# GUI Tooltips — Design Spec

**Task:** #49 — Add hover tooltips to buttons, checkboxes, sliders, and settings
**Date:** 2026-03-22

## Overview

Add hover tooltips to all interactive controls in the Python bot GUI and the WoW addon GUI. Restyle the existing Python `_Tooltip` class to match the dark theme. Use WoW's built-in `GameTooltip` for addon controls.

## Goals

1. Every interactive control has a tooltip explaining what it does
2. Tooltip length is mixed: short for obvious controls, medium for settings that need explanation
3. Python tooltips match the dark theme (not the current light yellow)
4. WoW addon tooltips use native GameTooltip styling
5. No new dependencies or widget classes

## Python Tooltip Style

Restyle `_Tooltip` in `widgets.py`:

| Property | Current | New |
|----------|---------|-----|
| Background | `#ffffe0` (light yellow) | `PANEL_DEEP` (`#0f3460`) |
| Text colour | `#333` | `TEXT_PRIMARY` (`#cccccc`) |
| Border | none | 1px `ACCENT` (`#00d4aa`) |
| Font | Segoe UI 8pt | Segoe UI 8pt (unchanged) |
| Max wrap | 300px | 300px (unchanged) |
| Position | rootx+20, rooty+height+4 | unchanged |

## WoW Addon Tooltip Pattern

Standard `GameTooltip` usage — no custom frames:

```lua
widget:SetScript("OnEnter", function(self)
    GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
    GameTooltip:SetText("Title", 1, 0.82, 0)
    GameTooltip:AddLine("Description text here.", 1, 1, 1, true)
    GameTooltip:Show()
end)
widget:SetScript("OnLeave", GameTooltip_Hide)
```

For CheckButtons that already have OnEnter/OnLeave scripts, use `HookScript` instead of `SetScript`.

## Tooltip Text — Python Main Window

| Control | Tooltip |
|---------|---------|
| Play/Stop button | Start/stop fishing (F6) |
| Pause button | Pause/resume fishing (F7) *(exists, restyle only)* |
| Calibrate button | Calibrate bobber colour detection *(exists, fix text — remove wrong "F6" hotkey reference)* |
| Compact toggle | Toggle compact mode *(exists, restyle only)* |
| Gear icon | Open settings |
| Addon status dot + label | Addon connection status — green when pixel bridge is active *(attach to `_addon_canvas` only, not the label)* |
| Fish header label | Click to open loot report in browser |
| Fish reset button | Reset fish count for this session |
| Log chevron | Collapse/expand log panel |

## Tooltip Text — Python Settings Popup

| Control | Tooltip |
|---------|---------|
| Cast key entry | Key the bot presses to cast. Must match your WoW action bar keybind |
| Lure key entry | Key for applying bait/lure. Leave empty for none |
| Loot wait slider | Random delay before looting after a bite. Adds human-like variation |
| Bite sensitivity slider | How strong a bobber dip must be to count as a bite. Lower = more sensitive, higher = fewer false positives |
| Colour multiplier slider | Scales bobber colour detection range. Higher = wider match, may pick up non-bobber reds |
| Colour closeness slider | How close a pixel must be to the target bobber colour. Higher = more lenient |
| Colour mode radios | Red for standard bobbers, Blue for special/blue bobbers |
| Auto-calibrate checkbox | Automatically calibrate bobber detection at the start of each session |
| Stop friendly checkbox | Stop fishing when a friendly player is detected nearby |
| Stop enemy checkbox | Stop fishing when an enemy player is detected nearby |
| Stop bags checkbox | Stop fishing when bags are full |
| Auto-delete checkbox | Automatically delete items on the addon's junk list |
| Always on top checkbox | Keep the bot window above other windows |
| Sound alerts checkbox | Play sounds for important events like whispers, nearby players, bags full |
| Debug screenshots checkbox | Save a screenshot when bobber detection fails, for troubleshooting |
| Pixel bar region button | Advanced — manually set the screen region where the addon pixel bar is located |
| Reset defaults button | Reset all settings to defaults |
| Colour preview chevron | Preview bobber colour detection |
| Capture button (colour preview) | Take a screenshot to preview colour detection |
| Live checkbox (colour preview) | Continuously update the colour preview |

## Tooltip Text — WoW Addon Settings Panel

| Control | Tooltip |
|---------|---------|
| Stop on friendly checkbox | Stop fishing when a friendly player is detected nearby |
| Stop on enemy checkbox | Stop fishing when an enemy player is detected nearby |
| Stop on bags full checkbox | Stop fishing when bags are full |
| Auto-delete checkbox | Automatically delete items on the junk list |
| Auto-calibrate checkbox | Automatically calibrate bobber detection at session start |
| Sound alerts checkbox | Play sounds for important events |
| Cast key button | Click then press a key to set the cast keybind |
| Lure key button | Click then press a key to set the lure keybind |
| Loot wait min slider | Minimum random delay before looting |
| Loot wait max slider | Maximum random delay before looting |
| Colour mode radios | Red for standard bobbers, Blue for special/blue bobbers |
| Colour multiplier slider | Scales bobber colour detection range |
| Colour closeness slider | How close a pixel must match the target bobber colour |
| Move Bar button | Drag the pixel bar to a new position |
| Reset Defaults button | Reset all settings to defaults |
| Skip party checkbox | Don't pause for party members |
| Skip guild checkbox | Don't pause for guild members |
| Skip friends checkbox | Don't pause for players on your friends list |

## Tooltip Text — WoW Addon Status Bar

FontStrings (`statusFrame.state`, `.line1`, `.line2`, `.line3`) cannot receive mouse scripts — they are not frames. Attach a single tooltip to the `statusFrame` itself:

| Element | Tooltip |
|---------|---------|
| statusFrame (the whole bar) | Drag to move. /lf status to toggle |

**Excluded:** Individual lines (state, caught, time/bags, alerts) — FontStrings can't have tooltips. The bar-level tooltip is sufficient.

## Implementation Notes

### Python `_Tooltip` helper

The existing `_Tooltip.__init__(widget, text)` API stays the same. Only the visual styling changes (background, text colour, border). Adding a tooltip to any widget is one line:

```python
_Tooltip(widget, "tooltip text here")
```

### WoW addon helper

Add a small helper to reduce boilerplate:

```lua
local function AddTooltip(widget, title, text)
    widget:HookScript("OnEnter", function(self)
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetText(title, 1, 0.82, 0)
        if text then
            GameTooltip:AddLine(text, 1, 1, 1, true)
        end
        GameTooltip:Show()
    end)
    widget:HookScript("OnLeave", function()
        GameTooltip:Hide()
    end)
end
```

Uses `HookScript` so it doesn't clobber existing `OnEnter`/`OnLeave` handlers (CheckButtons use these for highlight).

### Existing tooltips

Three tooltips already exist on Pause, Cal, and Compact buttons. Pause and Compact text stays the same. Cal tooltip text changes from "Calibrate bobber detection (F6 start/stop)" to "Calibrate bobber colour detection" — the F6 reference was wrong (F6 is the fishing toggle hotkey, Cal has no hotkey).

### Intentionally excluded

- **WoW addon Lists tab**: Add/Remove/Clear buttons and EditBox inputs are self-explanatory from their labels. No tooltips needed.
- **WoW addon tab buttons** (General/Lists/Detection): Standard tab navigation, no tooltip needed.
- **WoW addon close button**: Uses `UIPanelCloseButton` which has built-in WoW tooltip behaviour.
- **Python session timer label**: Non-interactive display, no tooltip.
- **Python bobber view canvas**: Main content area — tooltip would be intrusive.

## Files Changed

**Python:**
- `widgets.py` — restyle `_Tooltip` class (background, text colour, border)
- `gui.py` — add `_Tooltip()` calls to ~6 main window controls, fix Cal tooltip text
- `settings.py` — add `_Tooltip()` calls to ~19 settings controls

**WoW Addon:**
- `addon/Laksefisk/Laksefisk.lua` — add `AddTooltip` helper, add tooltip calls to ~18 settings controls + 1 status bar frame tooltip
