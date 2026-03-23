# Sliders Override Flag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send the addon's `slidersOverride` flag via the pixel bridge so the bot only applies addon colour slider values when the user has explicitly moved them in-game.

**Architecture:** Add one pixel (index 15) to row 2 encoding `slidersOverride`. The Python side reads this flag and skips applying colour multiplier/closeness values when it's false, letting the bot GUI or auto-calibration control detection instead.

**Tech Stack:** Lua (addon), Python (pixel_bridge.py, fishing_bot.py)

---

### Task 1: Encode slidersOverride in addon pixel bridge

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua:25` (ROW2_PIXELS constant)
- Modify: `addon/Laksefisk/Laksefisk.lua:449-452` (UpdateRow2Pixels, after pixel 35)

- [ ] **Step 1: Increase ROW2_PIXELS from 15 to 16**

```lua
local ROW2_PIXELS = 16      -- settings pixels in row 2
```

- [ ] **Step 2: Add slidersOverride encoding after pixel 35 (index 14)**

After the `SetRow2PixelRaw(14, ...)` line, add:

```lua
    -- [36] slidersOverride (index 15)
    SetRow2PixelRaw(15, db.slidersOverride and 255 or 0, 0, 0)
```

- [ ] **Step 3: Commit**

```bash
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat(addon): encode slidersOverride in pixel bridge row 2"
```

---

### Task 2: Decode slidersOverride in Python pixel bridge

**Files:**
- Modify: `pixel_bridge.py:129` (PixelBridgeData class — add field)
- Modify: `pixel_bridge.py:490-492` (read pixel 36 index 15, add to settings dict)
- Modify: `pixel_bridge.py:441` (map setting to data field)

- [ ] **Step 1: Add `s_sliders_override` field to PixelBridgeData**

After `s_calibration_toggle`:

```python
    s_sliders_override: bool = False
```

- [ ] **Step 2: Read pixel 36 (row2 index 15) in `_read_settings_row`**

After the `calibration_toggle` line (~line 492), add:

```python
        p36_r, _, _ = rp2(15)
```

- [ ] **Step 3: Add to settings return dict**

After `"calibration_toggle": calibration_toggle,` add:

```python
            "sliders_override": p36_r > 128,
```

- [ ] **Step 4: Map setting to data field**

After `data.s_calibration_toggle = settings["calibration_toggle"]` add:

```python
            data.s_sliders_override = settings["sliders_override"]
```

- [ ] **Step 5: Commit**

```bash
git add pixel_bridge.py
git commit -m "feat(bridge): decode slidersOverride from row 2 pixel 36"
```

---

### Task 3: Use slidersOverride in fishing bot

**Files:**
- Modify: `fishing_bot.py:148-160` (_apply_addon_settings — conditional slider application)

- [ ] **Step 1: Replace slider change detection with slidersOverride flag**

Replace lines 149-160 (the slider change detection and application block):

```python
        # Detect calibration request from addon button
        if self._last_cal_toggle is not None and data.s_calibration_toggle != self._last_cal_toggle:
            logger.info("Addon calibration request detected")
            self._calibrated = False  # triggers re-calibration on next cast
            self._use_addon_sliders = False
        self._last_cal_toggle = data.s_calibration_toggle
        # Detect manual slider changes — override calibration
        addon_mult = data.s_colour_multiplier
        addon_close = data.s_colour_closeness_multiplier
        if self._last_addon_mult is not None:
            if addon_mult != self._last_addon_mult or addon_close != self._last_addon_close:
                self._use_addon_sliders = True
        self._last_addon_mult = addon_mult
        self._last_addon_close = addon_close
        # Apply slider values to pixel classifier when not calibrated
        if self._use_addon_sliders and self._pixel_classifier:
            self._pixel_classifier.colour_multiplier = addon_mult
            self._pixel_classifier.colour_closeness_multiplier = addon_close
```

With:

```python
        # Detect calibration request from addon button
        if self._last_cal_toggle is not None and data.s_calibration_toggle != self._last_cal_toggle:
            logger.info("Addon calibration request detected")
            self._calibrated = False  # triggers re-calibration on next cast
        self._last_cal_toggle = data.s_calibration_toggle
        # Apply addon slider values only when user has explicitly moved them
        if data.s_sliders_override and self._pixel_classifier:
            self._pixel_classifier.colour_multiplier = data.s_colour_multiplier
            self._pixel_classifier.colour_closeness_multiplier = data.s_colour_closeness_multiplier
```

- [ ] **Step 2: Remove unused tracking fields from __init__**

Remove `_use_addon_sliders`, `_last_addon_mult`, `_last_addon_close` from `__init__` if they exist.

- [ ] **Step 3: Commit**

```bash
git add fishing_bot.py
git commit -m "feat(bot): only apply addon colour sliders when slidersOverride is true"
```

---

### Task 4: Copy addon to WoW and verify

- [ ] **Step 1: Copy updated addon to WoW folder**

```bash
cp addon/Laksefisk/Laksefisk.lua "/c/Program Files (x86)/World of Warcraft/_anniversary_/Interface/AddOns/Laksefisk/Laksefisk.lua"
```

- [ ] **Step 2: Manual test**

1. Start bot with auto-calibrate OFF, addon settings bar ON
2. Verify bot uses its own GUI colour slider values (not addon values)
3. Move a colour slider in the addon settings Detection tab
4. Verify bot switches to addon slider values
5. Click Calibrate button in addon
6. Verify bot re-calibrates and stops using addon slider values

- [ ] **Step 3: Final commit (if any fixes needed)**
