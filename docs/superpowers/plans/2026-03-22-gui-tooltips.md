# GUI Tooltips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hover tooltips to all interactive controls in both the Python bot GUI and the WoW addon GUI.

**Architecture:** Restyle the existing `_Tooltip` class in `widgets.py` to match the dark theme, then add `_Tooltip()` calls to all controls in `gui.py` and `settings.py`. For the WoW addon, add an `AddTooltip` Lua helper using `GameTooltip`, then wire it into the existing widget factory functions and standalone controls.

**Tech Stack:** Python tkinter, WoW Lua addon API (GameTooltip)

**Spec:** `docs/superpowers/specs/2026-03-22-gui-tooltips-design.md`

---

### Task 1: Restyle Python `_Tooltip` to dark theme

**Files:**
- Modify: `widgets.py:197-222`

- [ ] **Step 1: Update `_Tooltip._show` styling**

Change the Label styling in `_show` from light yellow to dark theme. In `widgets.py`, replace lines 214-216:

```python
        tk.Label(tw, text=self.text, justify="left", bg="#ffffe0", fg="#333",
                 relief="solid", bd=1, font=("Segoe UI", 8),
                 padx=6, pady=4, wraplength=300).pack()
```

With:

```python
        tk.Label(tw, text=self.text, justify="left",
                 bg=PANEL_DEEP, fg=TEXT_PRIMARY,
                 relief="flat", bd=0, font=("Segoe UI", 8),
                 padx=6, pady=4, wraplength=300).pack()
        tw.config(highlightbackground=ACCENT, highlightthickness=1)
```

This uses the constants already imported at the top of `widgets.py`. The `highlightbackground` on the Toplevel gives a 1px accent border.

- [ ] **Step 2: Verify constants are imported**

Check that `PANEL_DEEP`, `TEXT_PRIMARY`, and `ACCENT` are already imported in `widgets.py`. They are — line 14 imports them from `constants`.

- [ ] **Step 3: Commit**

```bash
git add widgets.py
git commit -m "feat: restyle tooltips to dark theme with accent border"
```

---

### Task 2: Add tooltips to Python main window controls

**Files:**
- Modify: `gui.py:228-304` (status bar controls), `gui.py:396-437` (fish/log controls)

The existing imports on line 52 already include `_Tooltip`. Three tooltips already exist (Pause line 245, Cal line 285, Compact line 304).

- [ ] **Step 1: Fix Cal button tooltip text**

In `gui.py` line 285, change:

```python
        _Tooltip(self._cal_btn, "Calibrate bobber detection (F6 start/stop)")
```

To:

```python
        _Tooltip(self._cal_btn, "Calibrate bobber colour detection")
```

The "F6" reference was wrong — F6 is the fishing toggle hotkey, Cal has no hotkey.

- [ ] **Step 2: Add tooltip to Play/Stop button**

After line 234 (`self._draw_toggle()`), add:

```python
        _Tooltip(self._toggle_canvas, "Start/stop fishing (F6)")
```

- [ ] **Step 3: Add tooltip to Gear icon**

After line 294 (`_bind_hover(gear, ...)`), add:

```python
        _Tooltip(gear, "Open settings")
```

- [ ] **Step 4: Add tooltip to Addon status dot**

After line 260 (`self._addon_dot = ...`), add:

```python
        _Tooltip(self._addon_canvas,
                 "Addon connection status \u2014 green when pixel bridge is active")
```

- [ ] **Step 5: Add tooltip to Fish header label**

After line 403 (the `webbrowser.open` bind), add:

```python
        _Tooltip(self._fish_header_label, "Click to open loot report in browser")
```

- [ ] **Step 6: Add tooltip to Fish reset button**

After line 409 (`reset_btn.pack(...)`), add:

```python
        _Tooltip(reset_btn, "Reset fish count for this session")
```

- [ ] **Step 7: Add tooltip to Log chevron**

After line 437 (`self._log_chevron.bind(...)`), add:

```python
        _Tooltip(self._log_chevron, "Collapse/expand log panel")
```

- [ ] **Step 8: Commit**

```bash
git add gui.py
git commit -m "feat: add tooltips to main window controls"
```

---

### Task 3: Add tooltips to Python settings popup

**Files:**
- Modify: `settings.py:23-27` (imports), `settings.py:58-310` (control creation)

- [ ] **Step 1: Import `_Tooltip` in settings.py**

In `settings.py` line 23-27, change:

```python
from widgets import (
    RangeSliderWithEntries,
    SliderWithEntry,
    _bind_hover,
)
```

To:

```python
from widgets import (
    RangeSliderWithEntries,
    SliderWithEntry,
    _Tooltip,
    _bind_hover,
)
```

- [ ] **Step 2: Add tooltips to key entries**

After line 78 (`e.bind("<KeyRelease>", self._on_cast_key)`) — the Cast Key entry, add:

```python
        _Tooltip(e, "Key the bot presses to cast. Must match your WoW action bar keybind")
```

After line 94 (`e.bind("<KeyRelease>", self._on_lure_key)`) — the Lure Key entry, add:

```python
        _Tooltip(e, "Key for applying bait/lure. Leave empty for none")
```

- [ ] **Step 3: Add tooltips to sliders**

After line 106 (`self._loot_range.grid(...)`) — Loot Wait range slider, add:

```python
        _Tooltip(self._loot_range,
                 "Random delay before looting after a bite. Adds human-like variation")
```

After line 115 (`self._bite_slider.grid(...)`) — Bite Sensitivity slider, add:

```python
        _Tooltip(self._bite_slider,
                 "How strong a bobber dip must be to count as a bite. "
                 "Lower = more sensitive, higher = fewer false positives")
```

After line 142 (`self._mult_slider.grid(...)`) — Colour Multiplier slider, add:

```python
        _Tooltip(self._mult_slider,
                 "Scales bobber colour detection range. "
                 "Higher = wider match, may pick up non-bobber reds")
```

After line 151 (`self._close_slider.grid(...)`) — Colour Closeness slider, add:

```python
        _Tooltip(self._close_slider,
                 "How close a pixel must be to the target bobber colour. Higher = more lenient")
```

- [ ] **Step 4: Add tooltips to radio buttons**

After line 133 (end of the Radiobutton `for` loop) — Colour Mode, add:

```python
        _Tooltip(mode_frame,
                 "Red for standard bobbers, Blue for special/blue bobbers")
```

Attaching to the parent `mode_frame` covers both radio buttons.

- [ ] **Step 5: Add tooltips to checkboxes**

The checkboxes are created inline with `.grid()` calls, so we need to capture the widget reference. Replace each checkbox block to store the widget. For each checkbox, change the pattern from:

```python
        tk.Checkbutton(
            container, text="...", variable=self._xxx_var,
            ...
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
```

To:

```python
        cb = tk.Checkbutton(
            container, text="...", variable=self._xxx_var,
            ...
        )
        cb.grid(row=row, column=0, columnspan=2, sticky="w", pady=1)
        _Tooltip(cb, "tooltip text")
```

Apply to all 8 checkboxes with these tooltip texts:

| Line | Variable | Tooltip |
|------|----------|---------|
| 160 | `_auto_cal_var` | Automatically calibrate bobber detection at the start of each session |
| 171 | `_stop_friendly_var` | Stop fishing when a friendly player is detected nearby |
| 182 | `_stop_enemy_var` | Stop fishing when an enemy player is detected nearby |
| 193 | `_stop_bags_var` | Stop fishing when bags are full |
| 204 | `_auto_delete_var` | Automatically delete items on the addon's junk list |
| 215 | `_topmost_var` | Keep the bot window above other windows |
| 226 | `_sound_var` | Play sounds for important events like whispers, nearby players, bags full |
| 237 | `_debug_ss_var` | Save a screenshot when bobber detection fails, for troubleshooting |

- [ ] **Step 6: Add tooltips to buttons and colour preview**

After line 254 (`_bind_hover(btn, PANEL_DEEP, ...)`) — Pixel Bar Region button, add:

```python
        _Tooltip(btn,
                 "Advanced \u2014 manually set the screen region where the addon pixel bar is located")
```

After line 264 (`_bind_hover(reset_btn, ALERT, ...)`) — Reset to Defaults button, add:

```python
        _Tooltip(reset_btn, "Reset all settings to defaults")
```

After line 274 (`self._preview_btn.grid(...)`) — Colour Preview chevron, add:

```python
        _Tooltip(self._preview_btn, "Preview bobber colour detection")
```

After line 288 (`_bind_hover(cap_btn, ...)`) — Capture button, add:

```python
        _Tooltip(cap_btn, "Take a screenshot to preview colour detection")
```

After line 295 (Live checkbox `.pack(side="left")`), the Live checkbox is also inline. Change:

```python
        tk.Checkbutton(
            btn_row, text="Live", variable=self._live_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP,
            command=self._toggle_live
        ).pack(side="left")
```

To:

```python
        live_cb = tk.Checkbutton(
            btn_row, text="Live", variable=self._live_var,
            bg=BG_DARK, fg=TEXT_PRIMARY, selectcolor=PANEL_BG,
            activebackground=PANEL_DEEP,
            command=self._toggle_live
        )
        live_cb.pack(side="left")
        _Tooltip(live_cb, "Continuously update the colour preview")
```

- [ ] **Step 7: Commit**

```bash
git add settings.py
git commit -m "feat: add tooltips to all settings popup controls"
```

---

### Task 4: Add tooltips to WoW addon GUI

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua`

- [ ] **Step 1: Add `AddTooltip` helper function**

After the `SetRow2PixelRaw` helper function (after line 117, before the `Bit` function), add:

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

- [ ] **Step 2: Add tooltip parameter to `CreateCheckbox`**

Change the `CreateCheckbox` function signature and add tooltip at the end. Current (line 555):

```lua
local function CreateCheckbox(parent, x, y, label, dbKey, onChange)
```

Change to:

```lua
local function CreateCheckbox(parent, x, y, label, dbKey, onChange, tooltip)
```

At the end of the function, before `return cb`, add:

```lua
    if tooltip then AddTooltip(cb, label, tooltip) end
```

- [ ] **Step 3: Add tooltip parameter to `CreateSettingSlider`**

Change the signature (line 571):

```lua
local function CreateSettingSlider(parent, x, y, label, dbKey, minVal, maxVal, step, displayFn)
```

To:

```lua
local function CreateSettingSlider(parent, x, y, label, dbKey, minVal, maxVal, step, displayFn, tooltip)
```

At the end, before `return container`, add:

```lua
    if tooltip then AddTooltip(container, label, tooltip) end
```

- [ ] **Step 4: Add tooltip parameter to `CreateKeyCaptureButton`**

Change the signature (line 606):

```lua
local function CreateKeyCaptureButton(parent, x, y, label, dbKey)
```

To:

```lua
local function CreateKeyCaptureButton(parent, x, y, label, dbKey, tooltip)
```

At the end, before `return container`, add:

```lua
    if tooltip then AddTooltip(container, label, tooltip) end
```

- [ ] **Step 5: Add tooltips to General tab checkbox calls**

Update the CreateCheckbox calls in `CreateSettingsPanel` (around lines 818-834):

```lua
    CreateCheckbox(generalTab, 0, yOff, "Stop on friendly player", "stopFriendly", nil,
        "Stop fishing when a friendly player is detected nearby")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Stop on enemy player", "stopEnemy", nil,
        "Stop fishing when an enemy player is detected nearby")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Stop on bags full", "stopBags", nil,
        "Stop fishing when bags are full")
    yOff = yOff - 28

    local featLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    featLabel:SetPoint("TOPLEFT", 0, yOff)
    featLabel:SetText("|cffff8000FEATURES|r")
    yOff = yOff - 16

    CreateCheckbox(generalTab, 0, yOff, "Auto-delete junk", "autoDelete", nil,
        "Automatically delete items on the junk list")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Auto-calibrate", "autoCalibrate", nil,
        "Automatically calibrate bobber detection at session start")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Sound alerts", "soundAlerts", nil,
        "Play sounds for important events")
```

- [ ] **Step 6: Add tooltips to key capture and slider calls**

Update key capture calls (around lines 842-844):

```lua
    CreateKeyCaptureButton(generalTab, 0, yOff, "Cast key", "castKeyIndex",
        "Click then press a key to set the cast keybind")
    yOff = yOff - 24
    CreateKeyCaptureButton(generalTab, 0, yOff, "Lure key", "lureKeyIndex",
        "Click then press a key to set the lure keybind")
```

Update slider calls (around lines 852-856):

```lua
    CreateSettingSlider(generalTab, 0, yOff, "Loot wait min", "lootWaitMin", 0, 15, 1,
        function(v) return string.format("%.1fs", v * 0.2) end,
        "Minimum random delay before looting")
    yOff = yOff - 40
    CreateSettingSlider(generalTab, 0, yOff, "Loot wait max", "lootWaitMax", 0, 15, 1,
        function(v) return string.format("%.1fs", v * 0.2) end,
        "Maximum random delay before looting")
```

- [ ] **Step 7: Add tooltips to Move Bar and Reset Defaults buttons**

After the existing `moveBarBtn:SetScript("OnClick", ...)` block (around line 866), add:

```lua
    AddTooltip(moveBarBtn, "Move Bar", "Drag the pixel bar to a new position")
```

After the existing `resetBtn:SetScript("OnClick", ...)` block closing `end)` (line 895), add:

```lua
    AddTooltip(resetBtn, "Reset Defaults", "Reset all settings to defaults")
```

- [ ] **Step 8: Add tooltips to Lists tab checkboxes**

Update the skip filter checkboxes (around lines 908-910):

```lua
    CreateCheckbox(listsTab, 0, -218, "Party members", "skipParty", nil,
        "Don't pause for party members")
    CreateCheckbox(listsTab, 0, -240, "Guild members", "skipGuild", nil,
        "Don't pause for guild members")
    CreateCheckbox(listsTab, 0, -262, "Friends list", "skipFriends", nil,
        "Don't pause for players on your friends list")
```

- [ ] **Step 9: Add tooltips to Detection tab controls**

After the radio button `OnClick` scripts (around lines 940-944), add:

```lua
    AddTooltip(redBtn, "Red", "Red for standard bobbers")
    AddTooltip(blueBtn, "Blue", "Blue for special/blue bobbers")
```

Update the detection slider calls (around lines 949-952):

```lua
    CreateSettingSlider(detectionTab, 0, -44, "Colour multiplier", "colourMult", 0, 15, 1,
        function(v) return string.format("%.1f", v * 0.2) end,
        "Scales bobber colour detection range")

    CreateSettingSlider(detectionTab, 0, -88, "Colour closeness", "colourClose", 0, 15, 1,
        function(v) return string.format("%.1f", v * (5.0 / 15)) end,
        "How close a pixel must match the target bobber colour")
```

- [ ] **Step 10: Add tooltip to status bar frame**

In `CreateStatusBar`, after the title font string setup (around line 1007), add:

```lua
    AddTooltip(statusFrame, "Laksefisk", "Drag to move. /lf status to toggle")
```

- [ ] **Step 11: Copy addon to WoW folder and commit**

```bash
cp "/c/Users/perzi/laksefisk/addon/Laksefisk/Laksefisk.lua" "/c/Program Files (x86)/World of Warcraft/_anniversary_/Interface/AddOns/Laksefisk/Laksefisk.lua"
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat: add GameTooltip to all addon settings and status bar controls"
```
