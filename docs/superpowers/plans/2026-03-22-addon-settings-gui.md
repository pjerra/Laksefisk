# Addon Settings GUI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-game WoW addon GUI (status bar + settings panel) and extend the pixel bar to a two-row layout so the bot can read settings from the addon.

**Architecture:** The addon gets a second pixel row (13 settings pixels below the existing 21 status pixels) plus two GUI frames (compact status bar and tabbed settings panel). The Python bot auto-detects the version marker pixel and reads settings from row 2 when present, falling back to local config for old addons.

**Tech Stack:** WoW Lua addon API (frames, textures, sliders, checkboxes, editboxes), Python (pixel_bridge.py dataclass extension, fishing_bot.py settings override)

**Spec:** `docs/superpowers/specs/2026-03-22-addon-settings-gui-design.md`

---

### Task 1: Add key index table to Python

**Files:**
- Modify: `pixel_bridge.py:30-36` (constants section)

This shared lookup table maps key indices (0-31) to Windows VK codes. The addon will have a matching Lua table.

- [ ] **Step 1: Add KEY_INDEX_TABLE constant**

Add after line 36 (after `SCAN_HEIGHT = 250`):

```python
# Shared key index → VK code table (must match Laksefisk.lua)
# Index 0 = None/unset
KEY_INDEX_TABLE = [
    None,   # 0: None
    0x31,   # 1: key "1"
    0x32,   # 2: key "2"
    0x33,   # 3: key "3"
    0x34,   # 4: key "4"
    0x35,   # 5: key "5"
    0x36,   # 6: key "6"
    0x37,   # 7: key "7"
    0x38,   # 8: key "8"
    0x39,   # 9: key "9"
    0x30,   # 10: key "0"
    0x70,   # 11: F1
    0x71,   # 12: F2
    0x72,   # 13: F3
    0x73,   # 14: F4
    0x74,   # 15: F5
    0x75,   # 16: F6
    0x76,   # 17: F7
    0x77,   # 18: F8
    0x78,   # 19: F9
    0x79,   # 20: F10
    0x7A,   # 21: F11
    0x7B,   # 22: F12
    0xBD,   # 23: -
    0xBB,   # 24: =
    0x60,   # 25: Num0
    0x61,   # 26: Num1
    0x6B,   # 27: Num+
    0x6D,   # 28: Num-
    0xC0,   # 29: `
    0xDB,   # 30: [
    0xDD,   # 31: ]
]
```

- [ ] **Step 2: Commit**

```bash
git add pixel_bridge.py
git commit -m "feat: add shared key index table for addon settings pixel bridge"
```

---

### Task 2: Extend PixelBridgeData with settings fields

**Files:**
- Modify: `pixel_bridge.py:47-66` (PixelBridgeData dataclass)

- [ ] **Step 1: Add settings fields to PixelBridgeData**

Add after `enemy_nearby: bool = False` (line 66):

```python
    # Addon version: 1 = old (21px), 2 = new (two-row, settings)
    addon_version: int = 1
    # Settings from addon (only populated when addon_version == 2)
    s_stop_friendly: bool = False
    s_stop_enemy: bool = False
    s_stop_bags: bool = False
    s_auto_delete: bool = False
    s_auto_calibrate: bool = False
    s_sound_alerts: bool = False
    s_colour_mode: str = "Red"       # "Red" or "Blue"
    s_skip_party: bool = False
    s_skip_guild: bool = False
    s_skip_friends: bool = False
    s_cast_key: Optional[int] = None       # VK code or None
    s_lure_key: Optional[int] = None       # VK code or None
    s_loot_wait_min: float = 0.6     # seconds
    s_loot_wait_max: float = 2.0     # seconds
    s_colour_multiplier: float = 0.6
    s_colour_closeness_multiplier: float = 2.0
```

Note: fields prefixed with `s_` to distinguish addon-sourced settings from bot status fields. Add `Optional` import if not present (it's already imported at line 23).

- [ ] **Step 2: Commit**

```bash
git add pixel_bridge.py
git commit -m "feat: add settings fields to PixelBridgeData for addon v2"
```

---

### Task 3: Add row 2 version detection and settings decoding

**Files:**
- Modify: `pixel_bridge.py:30-32` (constants)
- Modify: `pixel_bridge.py:238-332` (read method)

This is the core pixel bridge change. After reading row 1, check for the green version marker one pixel-height below, and if found, read and decode 13 settings pixels from row 2.

- [ ] **Step 1: Add version marker constant**

Add after `SYNC2 = (0, 255, 255)` (line 40):

```python
VERSION_MARKER_V2 = (0, 255, 0)  # green — pixel 21, identifies v2 addon
```

- [ ] **Step 2: Add decode helper for reading N bits across channels**

Add after `_decode_item_id` function (after line 169):

```python
def _read_bits_from_channels(img, bar_x, bar_y, pixel_size, pixel_step,
                              start_pixel, start_channel, num_bits, row_y_offset=0):
    """Read num_bits from consecutive RGB channels starting at given pixel/channel.

    Channels are numbered 0=R, 1=G, 2=B within each pixel, continuing across pixels.
    row_y_offset is added to bar_y for reading row 2.
    Returns integer value (MSB first).
    """
    bits = []
    px = start_pixel
    ch = start_channel
    adjusted_y = bar_y + row_y_offset
    for _ in range(num_bits):
        r, g, b = _read_pixel(img, bar_x, adjusted_y, px, pixel_size, pixel_step)
        channels = (r, g, b)
        bits.append(_read_bit(channels[ch]))
        ch += 1
        if ch >= 3:
            ch = 0
            px += 1
    value = 0
    for bit in bits:
        value = value * 2 + bit
    return value
```

- [ ] **Step 3: Add settings decode method to PixelBridge class**

Add as a new method in the PixelBridge class (after the `read` method, before `_capture_bottom_strip`):

```python
def _read_settings_row(self, img, bar_x, bar_y, px_size, px_step, row_y_offset):
    """Read settings from row 2 pixels. Returns dict of settings or None."""
    # Check version marker at row 2, pixel index 0 (= pixel 21 in spec)
    marker = _read_pixel(img, bar_x, bar_y + row_y_offset, 0, px_size, px_step)
    if not _colour_match(marker, VERSION_MARKER_V2):
        return None

    def rp2(idx):
        return _read_pixel(img, bar_x, bar_y + row_y_offset, idx, px_size, px_step)

    def bits(start_pixel, start_channel, num_bits):
        return _read_bits_from_channels(
            img, bar_x, bar_y, px_size, px_step,
            start_pixel, start_channel, num_bits,
            row_y_offset=row_y_offset
        )

    # Pixel 22 (index 1 in row 2): booleans
    p22_r, p22_g, p22_b = rp2(1)
    # Pixel 23 (index 2): booleans
    p23_r, p23_g, p23_b = rp2(2)
    # Pixel 24 (index 3): colour_mode, skip_party, skip_guild
    p24_r, p24_g, p24_b = rp2(3)
    # Pixel 25 (index 4): skip_friends + cast_key bits 4,3
    p25_r, _, _ = rp2(4)

    # 5-bit cast_key: pixel 25 channels G,B + pixel 26 channels R,G,B
    # That's index 4 channel 1 through index 5 channel 2 = 5 bits
    cast_key_idx = bits(4, 1, 5)  # row2 pixel index 4, channel G

    # 5-bit lure_key: pixel 27 channels R,G,B + pixel 28 R,G
    # That's index 6 channel 0 through index 7 channel 1 = 5 bits
    lure_key_idx = bits(6, 0, 5)  # row2 pixel index 6, channel R

    # 4-bit wait_min: pixel 28 B + pixel 29 R,G,B
    # That's index 7 channel 2 through index 8 channel 2 = 4 bits
    wait_min_raw = bits(7, 2, 4)

    # 4-bit wait_max: pixel 30 R,G,B + pixel 31 R
    # That's index 9 channel 0 through index 10 channel 0 = 4 bits
    wait_max_raw = bits(9, 0, 4)

    # 4-bit colour_mult: pixel 31 G,B + pixel 32 R,G
    # That's index 10 channel 1 through index 11 channel 1 = 4 bits
    col_mult_raw = bits(10, 1, 4)

    # 4-bit colour_close: pixel 32 B + pixel 33 R,G,B
    # That's index 11 channel 2 through index 12 channel 2 = 4 bits
    col_close_raw = bits(11, 2, 4)

    # Decode key indices to VK codes
    cast_vk = KEY_INDEX_TABLE[cast_key_idx] if cast_key_idx < len(KEY_INDEX_TABLE) else None
    lure_vk = KEY_INDEX_TABLE[lure_key_idx] if lure_key_idx < len(KEY_INDEX_TABLE) else None

    return {
        "stop_friendly": p22_r > 128,
        "stop_enemy": p22_g > 128,
        "stop_bags": p22_b > 128,
        "auto_delete": p23_r > 128,
        "auto_calibrate": p23_g > 128,
        "sound_alerts": p23_b > 128,
        "colour_mode": "Blue" if p24_r > 128 else "Red",
        "skip_party": p24_g > 128,
        "skip_guild": p24_b > 128,
        "skip_friends": p25_r > 128,
        "cast_key": cast_vk,
        "lure_key": lure_vk,
        "loot_wait_min": round(wait_min_raw * 0.2, 1),
        "loot_wait_max": round(wait_max_raw * 0.2, 1),
        "colour_multiplier": round(col_mult_raw * 0.2, 1),
        "colour_closeness_multiplier": round(col_close_raw * (5.0 / 15), 2),
    }
```

- [ ] **Step 4: Update the `read()` method to detect v2 and read row 2**

In the `read()` method, after the row 1 data is assembled (after `self._last_data = data`, around line 331), insert the version detection:

Replace the block from `self._last_data = data` to `return data` (lines 331-332) with:

```python
        # Check for v2 addon (row 2 settings)
        row2_offset = px_size  # one block height below row 1
        settings = self._read_settings_row(img, bar_x, bar_y, px_size, px_step, row2_offset)
        if settings:
            data.addon_version = 2
            data.s_stop_friendly = settings["stop_friendly"]
            data.s_stop_enemy = settings["stop_enemy"]
            data.s_stop_bags = settings["stop_bags"]
            data.s_auto_delete = settings["auto_delete"]
            data.s_auto_calibrate = settings["auto_calibrate"]
            data.s_sound_alerts = settings["sound_alerts"]
            data.s_colour_mode = settings["colour_mode"]
            data.s_skip_party = settings["skip_party"]
            data.s_skip_guild = settings["skip_guild"]
            data.s_skip_friends = settings["skip_friends"]
            data.s_cast_key = settings["cast_key"]
            data.s_lure_key = settings["lure_key"]
            data.s_loot_wait_min = settings["loot_wait_min"]
            data.s_loot_wait_max = settings["loot_wait_max"]
            data.s_colour_multiplier = settings["colour_multiplier"]
            data.s_colour_closeness_multiplier = settings["colour_closeness_multiplier"]

        self._last_data = data
        return data
```

- [ ] **Step 5: Update cached region height for two rows**

In the `read()` method, where `self._cached_region` is set (around line 274-279), change the height calculation:

Replace:
```python
                    "height": px_size + pad * 2,
```
With:
```python
                    "height": px_size * 2 + pad * 2,
```

This ensures the captured region is tall enough to include row 2 even before we know if it exists.

- [ ] **Step 6: Update module docstring**

Update the pixel layout comment at the top of `pixel_bridge.py` (lines 1-17) to mention row 2:

Add after line 16 (`[20]  Enemy flag — B channel = enemy_nearby`):
```python
#
# Row 2 (v2 addon only, detected by green version marker below row 1):
#   [21]  Version marker — green (0, 255, 0)
#   [22-33]  Settings (booleans, key indices, slider values)
#   See spec: docs/superpowers/specs/2026-03-22-addon-settings-gui-design.md
```

- [ ] **Step 7: Commit**

```bash
git add pixel_bridge.py
git commit -m "feat: add two-row pixel bar detection and settings decoding"
```

---

### Task 4: Apply addon settings in fishing_bot.py

**Files:**
- Modify: `fishing_bot.py:78-80` (stop conditions check area)

When `addon_version == 2`, the bot should apply settings from the pixel bridge data each time it reads. This happens in `_check_stop_conditions` which is called every cast loop iteration.

- [ ] **Step 1: Add settings application method to LaksefiskBot**

Add after the `set_lure_key` method (after line 119):

```python
    def _apply_addon_settings(self, data):
        """Apply settings from v2 addon pixel bridge data."""
        if data.addon_version != 2:
            return
        self.stop_on_friendly_nearby = data.s_stop_friendly
        self.stop_on_enemy_nearby = data.s_stop_enemy
        self.stop_on_bags_full = data.s_stop_bags
        self.auto_delete_junk = data.s_auto_delete
        self.auto_calibrate = data.s_auto_calibrate
        if data.s_cast_key is not None:
            self.cast_key = data.s_cast_key
        if data.s_lure_key is not None:
            self.lure_key = data.s_lure_key
        else:
            self.lure_key = None
        self.loot_wait_min = data.s_loot_wait_min
        self.loot_wait_max = data.s_loot_wait_max
```

Note: `colour_mode`, `colour_multiplier`, `colour_closeness_multiplier`, and `sound_alerts` are applied by the GUI layer (gui.py reads pixel bridge data and updates the relevant objects). The bot only needs the settings that directly affect its behaviour.

- [ ] **Step 2: Call _apply_addon_settings in _check_stop_conditions**

In `_check_stop_conditions`, after `self._dc_count = 0` (line 164), add:

```python
            # Apply addon settings if v2
            self._apply_addon_settings(data)
```

- [ ] **Step 3: Commit**

```bash
git add fishing_bot.py
git commit -m "feat: apply addon v2 settings from pixel bridge during fishing"
```

---

### Task 5: Add row 2 pixel blocks to Laksefisk.lua

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua`

This task adds the second row of pixel blocks to the addon. No settings encoding yet — just the pixel textures and version marker.

- [ ] **Step 1: Add row 2 constants**

After `local BAR_Y_OFFSET = 120` (line 24), add:

```lua
local ROW2_PIXELS = 13      -- settings pixels in row 2
```

- [ ] **Step 2: Add row 2 pixel array**

After `local pixels = {}` (line 73), add:

```lua
local row2pixels = {}
```

- [ ] **Step 3: Add SetRow2PixelRaw helper**

After the `SetPixelRaw` function (after line 84), add:

```lua
local function SetRow2PixelRaw(index, r, g, b)
    if row2pixels[index] then
        row2pixels[index]:SetColorTexture(r / 255, g / 255, b / 255, 1)
    end
end
```

- [ ] **Step 4: Create row 2 pixel blocks in CreatePixelBar**

In the `CreatePixelBar` function, after the existing pixel creation loop (after line 487, before `SetPixelRaw(0, 255, 0, 255)`), add:

```lua
    -- Row 2: settings pixels (below row 1)
    for i = 0, ROW2_PIXELS - 1 do
        local px = barFrame:CreateTexture(nil, "OVERLAY")
        px:SetSize(PIXEL_SIZE, PIXEL_SIZE)
        px:SetPoint("TOPLEFT", barFrame, "TOPLEFT", i * PIXEL_STEP, -PIXEL_SIZE)
        px:SetColorTexture(0, 0, 0, 1)
        row2pixels[i] = px
    end
```

Also update the barFrame height to accommodate two rows. Change:
```lua
    barFrame:SetSize(totalW, PIXEL_SIZE)
```
To:
```lua
    barFrame:SetSize(totalW, PIXEL_SIZE * 2)
```

And change the row 1 pixel anchoring from `"LEFT"` to `"TOPLEFT"` to prevent vertical centering shift when the frame grows:
```lua
        px:SetPoint("LEFT", barFrame, "LEFT", i * PIXEL_STEP, 0)
```
To:
```lua
        px:SetPoint("TOPLEFT", barFrame, "TOPLEFT", i * PIXEL_STEP, 0)
```

And update the move command height too (line 850):
```lua
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, 20)
```
To:
```lua
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, PIXEL_SIZE * 2 + 10)
```

And the lock restore (line 853):
```lua
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, PIXEL_SIZE)
```
To:
```lua
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, PIXEL_SIZE * 2)
```

- [ ] **Step 5: Set version marker in UpdateAllPixels**

At the end of `UpdateAllPixels()`, after `SetPixelRaw(20, 0, 0, enemyNearby and 255 or 0)` (line 311), add:

```lua
    -- Row 2: [21] Version marker — green
    SetRow2PixelRaw(0, 0, 255, 0)
```

- [ ] **Step 6: Commit**

```bash
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat: add row 2 pixel blocks and version marker to addon"
```

---

### Task 6: Add key index table and settings encoding to addon

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua`

Add the shared key index table in Lua and encode all settings into row 2 pixels.

- [ ] **Step 1: Add key index table**

After the state variables section (after line 70, before `local pixels = {}`), add:

```lua
-- Shared key index table (must match Python KEY_INDEX_TABLE)
-- Maps WoW key name → index for pixel encoding
local KEY_NAME_TO_INDEX = {
    ["1"] = 1, ["2"] = 2, ["3"] = 3, ["4"] = 4, ["5"] = 5,
    ["6"] = 6, ["7"] = 7, ["8"] = 8, ["9"] = 9, ["0"] = 10,
    ["F1"] = 11, ["F2"] = 12, ["F3"] = 13, ["F4"] = 14,
    ["F5"] = 15, ["F6"] = 16, ["F7"] = 17, ["F8"] = 18,
    ["F9"] = 19, ["F10"] = 20, ["F11"] = 21, ["F12"] = 22,
    ["-"] = 23, ["="] = 24,
    ["NUMPAD0"] = 25, ["NUMPAD1"] = 26, ["NUMPADADD"] = 27,
    ["NUMPADMINUS"] = 28, ["`"] = 29, ["["] = 30, ["]"] = 31,
}
-- Reverse: index → WoW key name (for display in GUI)
local KEY_INDEX_TO_NAME = {}
for name, idx in pairs(KEY_NAME_TO_INDEX) do
    KEY_INDEX_TO_NAME[idx] = name
end
KEY_INDEX_TO_NAME[0] = "None"
```

- [ ] **Step 2: Initialize settings defaults in PLAYER_LOGIN**

In the PLAYER_LOGIN handler (after `LaksefiskDB.skipFriends` init around line 526), add:

```lua
        -- Settings for pixel bridge (v2)
        if LaksefiskDB.stopFriendly == nil then LaksefiskDB.stopFriendly = false end
        if LaksefiskDB.stopEnemy == nil then LaksefiskDB.stopEnemy = false end
        if LaksefiskDB.stopBags == nil then LaksefiskDB.stopBags = false end
        if LaksefiskDB.autoDelete == nil then LaksefiskDB.autoDelete = false end
        if LaksefiskDB.autoCalibrate == nil then LaksefiskDB.autoCalibrate = false end
        if LaksefiskDB.soundAlerts == nil then LaksefiskDB.soundAlerts = false end
        if LaksefiskDB.colourMode == nil then LaksefiskDB.colourMode = 0 end  -- 0=Red, 1=Blue
        if LaksefiskDB.castKeyIndex == nil then LaksefiskDB.castKeyIndex = 4 end  -- key "4"
        if LaksefiskDB.lureKeyIndex == nil then LaksefiskDB.lureKeyIndex = 0 end  -- None
        if LaksefiskDB.lootWaitMin == nil then LaksefiskDB.lootWaitMin = 3 end  -- index 3 = 0.6s
        if LaksefiskDB.lootWaitMax == nil then LaksefiskDB.lootWaitMax = 10 end -- index 10 = 2.0s
        if LaksefiskDB.colourMult == nil then LaksefiskDB.colourMult = 3 end   -- index 3 = 0.6
        if LaksefiskDB.colourClose == nil then LaksefiskDB.colourClose = 6 end -- index 6 = 2.0
```

- [ ] **Step 3: Add UpdateRow2Pixels function**

After `UpdateAllPixels()`, add:

```lua
local function UpdateRow2Pixels()
    local db = LaksefiskDB

    -- [21] Version marker — green (pixel index 0 in row 2)
    SetRow2PixelRaw(0, 0, 255, 0)

    -- [22] Booleans: stop_friendly, stop_enemy, stop_bags (index 1)
    SetRow2PixelRaw(1,
        db.stopFriendly and 255 or 0,
        db.stopEnemy and 255 or 0,
        db.stopBags and 255 or 0
    )

    -- [23] Booleans: auto_delete, auto_calibrate, sound_alerts (index 2)
    SetRow2PixelRaw(2,
        db.autoDelete and 255 or 0,
        db.autoCalibrate and 255 or 0,
        db.soundAlerts and 255 or 0
    )

    -- [24] colour_mode, skip_party, skip_guild (index 3)
    SetRow2PixelRaw(3,
        db.colourMode == 1 and 255 or 0,
        db.skipParty and 255 or 0,
        db.skipGuild and 255 or 0
    )

    -- [25-26] skip_friends + cast_key (5-bit) (indices 4-5)
    -- Pixel 25: R=skip_friends, G=castKey[4], B=castKey[3]
    local ck = db.castKeyIndex or 0
    SetRow2PixelRaw(4,
        db.skipFriends and 255 or 0,
        Bit(ck, 4),
        Bit(ck, 3)
    )
    -- Pixel 26: R=castKey[2], G=castKey[1], B=castKey[0]
    SetRow2PixelRaw(5, Bit(ck, 2), Bit(ck, 1), Bit(ck, 0))

    -- [27-28] lure_key (5-bit) (indices 6-7)
    local lk = db.lureKeyIndex or 0
    -- Pixel 27: R=lureKey[4], G=lureKey[3], B=lureKey[2]
    SetRow2PixelRaw(6, Bit(lk, 4), Bit(lk, 3), Bit(lk, 2))
    -- Pixel 28: R=lureKey[1], G=lureKey[0], B=waitMin[3]
    local wmin = db.lootWaitMin or 0
    SetRow2PixelRaw(7, Bit(lk, 1), Bit(lk, 0), Bit(wmin, 3))

    -- [29] wait_min bits 2,1,0 (index 8)
    SetRow2PixelRaw(8, Bit(wmin, 2), Bit(wmin, 1), Bit(wmin, 0))

    -- [30] wait_max bits 3,2,1 (index 9)
    local wmax = db.lootWaitMax or 0
    SetRow2PixelRaw(9, Bit(wmax, 3), Bit(wmax, 2), Bit(wmax, 1))

    -- [31] wait_max[0], col_mult[3], col_mult[2] (index 10)
    local cm = db.colourMult or 0
    SetRow2PixelRaw(10, Bit(wmax, 0), Bit(cm, 3), Bit(cm, 2))

    -- [32] col_mult[1], col_mult[0], col_close[3] (index 11)
    local cc = db.colourClose or 0
    SetRow2PixelRaw(11, Bit(cm, 1), Bit(cm, 0), Bit(cc, 3))

    -- [33] col_close[2], col_close[1], col_close[0] (index 12)
    SetRow2PixelRaw(12, Bit(cc, 2), Bit(cc, 1), Bit(cc, 0))
end
```

- [ ] **Step 4: Call UpdateRow2Pixels in the OnUpdate loop**

In the OnUpdate handler (line 634), after `UpdateAllPixels()`, add:

```lua
        UpdateRow2Pixels()
```

- [ ] **Step 5: Update version number in header comment**

Change line 1:
```lua
-- Laksefisk Pixel Bridge v8
```
To:
```lua
-- Laksefisk Pixel Bridge v9
```

Update the login print to show v9 and row count:
```lua
        print("|cff4FC3F7Laksefisk|r pixel bridge v9 loaded (" .. NUM_PIXELS .. "+" .. ROW2_PIXELS .. " pixels, " .. nDel .. " auto-delete, containers " .. cStr .. ")")
```

- [ ] **Step 6: Commit**

```bash
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat: encode bot settings in row 2 pixels with key index table"
```

---

### Task 7: Add status bar GUI frame to addon

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua`

Add the compact status bar that shows fishing state, catch count, last item, session time, bags, and alerts.

- [ ] **Step 1: Add session tracking variables**

After the state variables (after `local junkOnCursor = false`, line 48), add:

```lua
local sessionStartTime = nil   -- GetTime() when first cast happened
local showStatusBar = false
local statusFrame = nil
```

- [ ] **Step 2: Add GetTotalBagSlots helper**

After `GetFreeBagSlots` (after line 99), add:

```lua
local function GetTotalBagSlots()
    local total = 0
    for bag = 0, 4 do
        local slots = C_Container and C_Container.GetContainerNumSlots(bag)
                      or GetContainerNumSlots(bag)
        total = total + (slots or 0)
    end
    return total
end
```

- [ ] **Step 3: Add FormatDuration helper**

```lua
local function FormatDuration(seconds)
    if not seconds or seconds < 0 then return "0m" end
    local h = math.floor(seconds / 3600)
    local m = math.floor((seconds % 3600) / 60)
    if h > 0 then return string.format("%dh %dm", h, m) end
    return string.format("%dm", m)
end
```

- [ ] **Step 4: Create the status bar frame**

Add a `CreateStatusBar` function (before `CreatePixelBar`):

```lua
local function CreateStatusBar()
    statusFrame = CreateFrame("Frame", "LaksefiskStatus", UIParent, "BackdropTemplate")
    statusFrame:SetSize(240, 80)
    statusFrame:SetPoint("TOP", UIParent, "TOP", 0, -20)
    statusFrame:SetFrameStrata("HIGH")
    statusFrame:SetBackdrop({
        bgFile = "Interface\\Buttons\\WHITE8x8",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        edgeSize = 12,
        insets = { left = 2, right = 2, top = 2, bottom = 2 },
    })
    statusFrame:SetBackdropColor(0.08, 0.08, 0.08, 0.9)
    statusFrame:SetBackdropBorderColor(0.4, 0.35, 0.2, 1)

    -- Draggable
    statusFrame:SetMovable(true)
    statusFrame:EnableMouse(true)
    statusFrame:RegisterForDrag("LeftButton")
    statusFrame:SetScript("OnDragStart", function(self) self:StartMoving() end)
    statusFrame:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        local x, y = self:GetLeft(), self:GetBottom()
        if x and y then
            LaksefiskDB.statusPos = { x = x, y = y }
            self:ClearAllPoints()
            self:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", x, y)
        end
    end)

    -- Title
    statusFrame.title = statusFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statusFrame.title:SetPoint("TOPLEFT", 8, -6)
    statusFrame.title:SetText("|cffff8000Laksefisk|r")

    -- State label
    statusFrame.state = statusFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    statusFrame.state:SetPoint("TOPRIGHT", -8, -6)

    -- Line 1: Caught / Last item
    statusFrame.line1 = statusFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    statusFrame.line1:SetPoint("TOPLEFT", 8, -22)
    statusFrame.line1:SetWidth(224)
    statusFrame.line1:SetJustifyH("LEFT")

    -- Line 2: Time / Bags
    statusFrame.line2 = statusFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    statusFrame.line2:SetPoint("TOPLEFT", 8, -36)
    statusFrame.line2:SetWidth(224)
    statusFrame.line2:SetJustifyH("LEFT")

    -- Line 3: Alerts
    statusFrame.line3 = statusFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    statusFrame.line3:SetPoint("TOPLEFT", 8, -50)
    statusFrame.line3:SetWidth(224)
    statusFrame.line3:SetJustifyH("LEFT")

    -- Restore position
    local saved = LaksefiskDB.statusPos
    if saved and saved.x and saved.y then
        statusFrame:ClearAllPoints()
        statusFrame:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", saved.x, saved.y)
    end

    statusFrame:Hide()
end
```

- [ ] **Step 5: Add UpdateStatusBar function**

```lua
local function UpdateStatusBar()
    if not statusFrame or not showStatusBar then return end

    -- State
    local stateText, stateColor
    if isDead then
        stateText = "Dead"
        stateColor = "|cffff4444"
    elseif UnitAffectingCombat("player") then
        stateText = "Combat"
        stateColor = "|cffff8800"
    elseif isFishing then
        stateText = "Fishing"
        stateColor = "|cff44ff44"
    else
        stateText = "Idle"
        stateColor = "|cff888888"
    end
    statusFrame.state:SetText(stateColor .. stateText .. "|r")

    -- Line 1: Caught + last item
    local itemStr = lastItemName ~= "" and ("|cff1eff00" .. lastItemName .. "|r") or ""
    statusFrame.line1:SetText("Caught: |cffffffff" .. lootCounter .. "|r  " .. itemStr)

    -- Line 2: Time + bags
    local duration = sessionStartTime and (GetTime() - sessionStartTime) or 0
    local free = GetFreeBagSlots()
    local total = GetTotalBagSlots()
    local used = total - free
    statusFrame.line2:SetText("Time: |cffffffff" .. FormatDuration(duration) .. "|r  Bags: |cffffffff" .. used .. "/" .. total .. "|r")

    -- Line 3: Alerts
    local alerts = {}
    if playerNearby then table.insert(alerts, "|cffff4444Player nearby|r") end
    if enemyNearby then table.insert(alerts, "|cffff4444Enemy nearby|r") end
    if GetFreeBagSlots() <= 2 then table.insert(alerts, "|cffffcc00Bags full|r") end
    statusFrame.line3:SetText(#alerts > 0 and table.concat(alerts, "  ") or "")
end
```

- [ ] **Step 6: Set session start time on first cast**

In the `UNIT_SPELLCAST_CHANNEL_START` handler (around line 576), after `castCounter = castCounter + 1`, add:

```lua
                if not sessionStartTime then
                    sessionStartTime = GetTime()
                end
```

- [ ] **Step 7: Call CreateStatusBar on login and update in OnUpdate**

In PLAYER_LOGIN handler, after `CreatePixelBar()`, add:

```lua
        CreateStatusBar()
        -- Restore status bar visibility
        if LaksefiskDB.showStatusBar then
            showStatusBar = true
            if statusFrame then statusFrame:Show() end
        end
```

In the OnUpdate handler (line 634), after `UpdateRow2Pixels()`, add:

```lua
        UpdateStatusBar()
```

- [ ] **Step 8: Add /lf status command**

In the slash command handler, before the `else` (help) block, add:

```lua
    elseif cmd == "status" then
        showStatusBar = not showStatusBar
        LaksefiskDB.showStatusBar = showStatusBar
        if showStatusBar then
            if statusFrame then statusFrame:Show() end
        else
            if statusFrame then statusFrame:Hide() end
        end
```

- [ ] **Step 9: Commit**

```bash
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat: add compact status bar GUI to addon"
```

---

### Task 8: Add settings panel GUI frame to addon — General tab

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua`

Create the settings panel frame with the General tab (stop conditions, features, keys, timing, pixel bar move, reset).

- [ ] **Step 1: Add settings panel variables**

After the status bar variables, add:

```lua
local showSettingsPanel = false
local settingsFrame = nil
local activeTab = 1  -- 1=General, 2=Lists, 3=Detection
```

- [ ] **Step 2: Create helper function for WoW checkboxes**

Add before `CreateStatusBar`:

```lua
local function CreateCheckbox(parent, x, y, label, dbKey, onChange)
    local cb = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
    cb:SetPoint("TOPLEFT", x, y)
    cb:SetSize(22, 22)
    cb.text = cb:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    cb.text:SetPoint("LEFT", cb, "RIGHT", 2, 0)
    cb.text:SetText(label)
    cb:SetChecked(LaksefiskDB[dbKey] and true or false)
    cb:SetScript("OnClick", function(self)
        LaksefiskDB[dbKey] = self:GetChecked() and true or false
        if onChange then onChange(LaksefiskDB[dbKey]) end
    end)
    cb.dbKey = dbKey
    return cb
end
```

- [ ] **Step 3: Create helper for WoW sliders**

```lua
local function CreateSettingSlider(parent, x, y, label, dbKey, minVal, maxVal, step, displayFn)
    local container = CreateFrame("Frame", nil, parent)
    container:SetPoint("TOPLEFT", x, y)
    container:SetSize(200, 36)

    local text = container:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    text:SetPoint("TOPLEFT", 0, 0)

    local slider = CreateFrame("Slider", nil, container, "OptionsSliderTemplate")
    slider:SetPoint("TOPLEFT", 0, -14)
    slider:SetSize(180, 16)
    slider:SetMinMaxValues(minVal, maxVal)
    slider:SetValueStep(step)
    slider:SetObeyStepOnDrag(true)
    slider:SetValue(LaksefiskDB[dbKey] or minVal)
    slider.Low:SetText("")
    slider.High:SetText("")

    local function updateText()
        local val = slider:GetValue()
        text:SetText(label .. ": |cffffffff" .. (displayFn and displayFn(val) or tostring(val)) .. "|r")
    end
    updateText()

    slider:SetScript("OnValueChanged", function(self, val)
        val = math.floor(val / step + 0.5) * step  -- snap to step
        LaksefiskDB[dbKey] = val
        updateText()
    end)

    container.slider = slider
    container.dbKey = dbKey
    return container
end
```

- [ ] **Step 4: Create key capture button helper**

```lua
local function CreateKeyCaptureButton(parent, x, y, label, dbKey)
    local container = CreateFrame("Frame", nil, parent)
    container:SetPoint("TOPLEFT", x, y)
    container:SetSize(200, 20)

    local text = container:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    text:SetPoint("LEFT", 0, 0)
    text:SetText(label .. ": ")

    local btn = CreateFrame("Button", nil, container, "UIPanelButtonTemplate")
    btn:SetPoint("LEFT", text, "RIGHT", 4, 0)
    btn:SetSize(60, 20)

    local idx = LaksefiskDB[dbKey] or 0
    btn:SetText(KEY_INDEX_TO_NAME[idx] or "None")

    local capturing = false
    btn:SetScript("OnClick", function()
        capturing = true
        btn:SetText("|cffFFFF00Press key...|r")
    end)
    btn:SetScript("OnKeyDown", function(self, key)
        if not capturing then return end
        capturing = false
        if key == "ESCAPE" then
            -- Cancel capture
            local curIdx = LaksefiskDB[dbKey] or 0
            btn:SetText(KEY_INDEX_TO_NAME[curIdx] or "None")
            return
        end
        local keyIdx = KEY_NAME_TO_INDEX[key]
        if keyIdx then
            LaksefiskDB[dbKey] = keyIdx
            btn:SetText(KEY_INDEX_TO_NAME[keyIdx] or key)
        else
            -- Unsupported key
            local curIdx = LaksefiskDB[dbKey] or 0
            btn:SetText(KEY_INDEX_TO_NAME[curIdx] or "None")
        end
    end)
    btn:EnableKeyboard(true)

    container.btn = btn
    container.dbKey = dbKey
    return container
end
```

- [ ] **Step 5: Create the settings panel frame with General tab**

```lua
local generalTab, listsTab, detectionTab  -- tab content frames

local function CreateSettingsPanel()
    settingsFrame = CreateFrame("Frame", "LaksefiskSettings", UIParent, "BackdropTemplate")
    settingsFrame:SetSize(260, 340)
    settingsFrame:SetPoint("CENTER")
    settingsFrame:SetFrameStrata("DIALOG")
    settingsFrame:SetBackdrop({
        bgFile = "Interface\\Buttons\\WHITE8x8",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        edgeSize = 12,
        insets = { left = 2, right = 2, top = 2, bottom = 2 },
    })
    settingsFrame:SetBackdropColor(0.08, 0.08, 0.08, 0.95)
    settingsFrame:SetBackdropBorderColor(0.4, 0.35, 0.2, 1)

    -- Esc to close
    tinsert(UISpecialFrames, "LaksefiskSettings")

    -- Draggable
    settingsFrame:SetMovable(true)
    settingsFrame:EnableMouse(true)
    settingsFrame:RegisterForDrag("LeftButton")
    settingsFrame:SetScript("OnDragStart", function(self) self:StartMoving() end)
    settingsFrame:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        local x, y = self:GetLeft(), self:GetBottom()
        if x and y then
            LaksefiskDB.settingsPos = { x = x, y = y }
            self:ClearAllPoints()
            self:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", x, y)
        end
    end)

    -- Title
    local title = settingsFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", 10, -8)
    title:SetText("|cffffd100Laksefisk Settings|r")

    -- Close button
    local closeBtn = CreateFrame("Button", nil, settingsFrame, "UIPanelCloseButton")
    closeBtn:SetPoint("TOPRIGHT", -2, -2)
    closeBtn:SetScript("OnClick", function()
        showSettingsPanel = false
        settingsFrame:Hide()
    end)

    -- Tab buttons
    local tabNames = {"General", "Lists", "Detection"}
    local tabButtons = {}
    for i, name in ipairs(tabNames) do
        local tab = CreateFrame("Button", nil, settingsFrame)
        tab:SetSize(75, 22)
        tab:SetPoint("TOPLEFT", 8 + (i - 1) * 78, -28)
        tab.text = tab:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        tab.text:SetPoint("CENTER")
        tab.text:SetText(name)
        tab.bg = tab:CreateTexture(nil, "BACKGROUND")
        tab.bg:SetAllPoints()
        tab:SetScript("OnClick", function()
            activeTab = i
            LaksefiskDB.activeTab = i
            UpdateSettingsTabs()
        end)
        tabButtons[i] = tab
    end

    -- Tab content area
    local contentArea = CreateFrame("Frame", nil, settingsFrame)
    contentArea:SetPoint("TOPLEFT", 8, -54)
    contentArea:SetPoint("BOTTOMRIGHT", -8, 8)

    -- General tab content
    generalTab = CreateFrame("Frame", nil, contentArea)
    generalTab:SetAllPoints()

    local yOff = 0
    local sectionLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    sectionLabel:SetPoint("TOPLEFT", 0, yOff)
    sectionLabel:SetText("|cffff8000STOP CONDITIONS|r")
    yOff = yOff - 16

    CreateCheckbox(generalTab, 0, yOff, "Stop on friendly player", "stopFriendly")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Stop on enemy player", "stopEnemy")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Stop on bags full", "stopBags")
    yOff = yOff - 28

    local featLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    featLabel:SetPoint("TOPLEFT", 0, yOff)
    featLabel:SetText("|cffff8000FEATURES|r")
    yOff = yOff - 16

    CreateCheckbox(generalTab, 0, yOff, "Auto-delete junk", "autoDelete")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Auto-calibrate", "autoCalibrate")
    yOff = yOff - 22
    CreateCheckbox(generalTab, 0, yOff, "Sound alerts", "soundAlerts")
    yOff = yOff - 28

    local keysLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    keysLabel:SetPoint("TOPLEFT", 0, yOff)
    keysLabel:SetText("|cffff8000KEYS|r")
    yOff = yOff - 16

    CreateKeyCaptureButton(generalTab, 0, yOff, "Cast key", "castKeyIndex")
    yOff = yOff - 24
    CreateKeyCaptureButton(generalTab, 0, yOff, "Lure key", "lureKeyIndex")
    yOff = yOff - 32

    local timingLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    timingLabel:SetPoint("TOPLEFT", 0, yOff)
    timingLabel:SetText("|cffff8000TIMING|r")
    yOff = yOff - 16

    CreateSettingSlider(generalTab, 0, yOff, "Loot wait min", "lootWaitMin", 0, 15, 1,
        function(v) return string.format("%.1fs", v * 0.2) end)
    yOff = yOff - 40
    CreateSettingSlider(generalTab, 0, yOff, "Loot wait max", "lootWaitMax", 0, 15, 1,
        function(v) return string.format("%.1fs", v * 0.2) end)

    settingsFrame:Hide()

    -- Restore position
    local saved = LaksefiskDB.settingsPos
    if saved and saved.x and saved.y then
        settingsFrame:ClearAllPoints()
        settingsFrame:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", saved.x, saved.y)
    end
end

local UpdateSettingsTabs  -- forward declaration (used by tab buttons before definition)
-- ... (place this before CreateSettingsPanel)

UpdateSettingsTabs = function()
    if not settingsFrame then return end
    if generalTab then generalTab:SetShown(activeTab == 1) end
    if listsTab then listsTab:SetShown(activeTab == 2) end
    if detectionTab then detectionTab:SetShown(activeTab == 3) end
end
```

- [ ] **Step 6: Add /lf settings command and call CreateSettingsPanel on login**

In PLAYER_LOGIN, after `CreateStatusBar()`, add:
```lua
        CreateSettingsPanel()
        activeTab = LaksefiskDB.activeTab or 1
        UpdateSettingsTabs()
```

In slash commands, before the `else` (help) block, add:
```lua
    elseif cmd == "settings" then
        showSettingsPanel = not showSettingsPanel
        if showSettingsPanel then
            if settingsFrame then settingsFrame:Show() end
        else
            if settingsFrame then settingsFrame:Hide() end
        end
```

- [ ] **Step 7: Commit**

```bash
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat: add settings panel with General tab to addon"
```

---

### Task 9: Add Lists tab to settings panel

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua`

Add the Lists tab with delete list management, whitelist management, and skip filter checkboxes.

- [ ] **Step 1: Create scrollable list helper**

Add before `CreateSettingsPanel`:

```lua
local function CreateEditableList(parent, x, y, height, label, dbKey)
    local container = CreateFrame("Frame", nil, parent)
    container:SetPoint("TOPLEFT", x, y)
    container:SetSize(230, height)

    local text = container:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    text:SetPoint("TOPLEFT", 0, 0)
    text:SetText("|cffff8000" .. label .. "|r")

    -- Scroll frame for list items
    local scrollFrame = CreateFrame("ScrollFrame", nil, container, "UIPanelScrollFrameTemplate")
    scrollFrame:SetPoint("TOPLEFT", 0, -16)
    scrollFrame:SetSize(210, height - 46)

    local content = CreateFrame("Frame", nil, scrollFrame)
    content:SetSize(200, 1)
    scrollFrame:SetScrollChild(content)

    -- Input row
    local editBox = CreateFrame("EditBox", nil, container, "InputBoxTemplate")
    editBox:SetPoint("BOTTOMLEFT", 0, 0)
    editBox:SetSize(140, 20)
    editBox:SetAutoFocus(false)

    local addBtn = CreateFrame("Button", nil, container, "UIPanelButtonTemplate")
    addBtn:SetPoint("LEFT", editBox, "RIGHT", 4, 0)
    addBtn:SetSize(40, 20)
    addBtn:SetText("Add")

    local clearBtn = CreateFrame("Button", nil, container, "UIPanelButtonTemplate")
    clearBtn:SetPoint("LEFT", addBtn, "RIGHT", 2, 0)
    clearBtn:SetSize(42, 20)
    clearBtn:SetText("Clear")

    local function RefreshList()
        -- Clear existing children
        for _, child in pairs({content:GetChildren()}) do
            child:Hide()
            child:SetParent(nil)
        end
        local list = LaksefiskDB[dbKey] or {}
        local yPos = 0
        for i, name in ipairs(list) do
            local row = CreateFrame("Frame", nil, content)
            row:SetSize(200, 16)
            row:SetPoint("TOPLEFT", 0, -yPos)
            local nameStr = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
            nameStr:SetPoint("LEFT", 2, 0)
            nameStr:SetText(name)
            local removeBtn = CreateFrame("Button", nil, row)
            removeBtn:SetSize(14, 14)
            removeBtn:SetPoint("RIGHT", -2, 0)
            removeBtn:SetNormalTexture("Interface\\Buttons\\UI-StopButton")
            removeBtn:SetScript("OnClick", function()
                table.remove(LaksefiskDB[dbKey], i)
                RefreshList()
            end)
            yPos = yPos + 16
        end
        content:SetHeight(math.max(1, yPos))
    end

    addBtn:SetScript("OnClick", function()
        local val = editBox:GetText()
        if val and val ~= "" then
            val = string.match(val, "%[(.-)%]") or val
            val = val:gsub("^%s+", ""):gsub("%s+$", "")
            if val ~= "" then
                LaksefiskDB[dbKey] = LaksefiskDB[dbKey] or {}
                table.insert(LaksefiskDB[dbKey], val)
                editBox:SetText("")
                RefreshList()
            end
        end
    end)

    editBox:SetScript("OnEnterPressed", function()
        addBtn:Click()
    end)

    clearBtn:SetScript("OnClick", function()
        LaksefiskDB[dbKey] = {}
        RefreshList()
    end)

    container.Refresh = RefreshList
    C_Timer.After(0, RefreshList)  -- initial populate

    return container
end
```

- [ ] **Step 2: Create Lists tab content in CreateSettingsPanel**

After the General tab creation (after `generalTab` content), add:

```lua
    -- Lists tab content
    listsTab = CreateFrame("Frame", nil, contentArea)
    listsTab:SetAllPoints()

    CreateEditableList(listsTab, 0, 0, 100, "AUTO-DELETE LIST", "deleteList")
    CreateEditableList(listsTab, 0, -106, 90, "PLAYER WHITELIST", "whitelist")

    local skipLabel = listsTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    skipLabel:SetPoint("TOPLEFT", 0, -202)
    skipLabel:SetText("|cffff8000AUTO-SKIP (don't pause for)|r")

    CreateCheckbox(listsTab, 0, -218, "Party members", "skipParty")
    CreateCheckbox(listsTab, 0, -240, "Guild members", "skipGuild")
    CreateCheckbox(listsTab, 0, -262, "Friends list", "skipFriends")
```

- [ ] **Step 3: Commit**

```bash
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat: add Lists tab to settings panel (delete list, whitelist, skip filters)"
```

---

### Task 10: Add Detection tab to settings panel

**Files:**
- Modify: `addon/Laksefisk/Laksefisk.lua`

- [ ] **Step 1: Create Detection tab content**

After the Lists tab creation, add:

```lua
    -- Detection tab content
    detectionTab = CreateFrame("Frame", nil, contentArea)
    detectionTab:SetAllPoints()

    local colourLabel = detectionTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    colourLabel:SetPoint("TOPLEFT", 0, 0)
    colourLabel:SetText("|cffff8000COLOUR MODE|r")

    local redBtn = CreateFrame("CheckButton", nil, detectionTab, "UIRadioButtonTemplate")
    redBtn:SetPoint("TOPLEFT", 0, -16)
    redBtn:SetSize(20, 20)
    redBtn.text = redBtn:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    redBtn.text:SetPoint("LEFT", redBtn, "RIGHT", 2, 0)
    redBtn.text:SetText("|cffff4444Red|r")

    local blueBtn = CreateFrame("CheckButton", nil, detectionTab, "UIRadioButtonTemplate")
    blueBtn:SetPoint("TOPLEFT", 100, -16)
    blueBtn:SetSize(20, 20)
    blueBtn.text = blueBtn:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    blueBtn.text:SetPoint("LEFT", blueBtn, "RIGHT", 2, 0)
    blueBtn.text:SetText("|cff4444ffBlue|r")

    local function UpdateRadios()
        redBtn:SetChecked(LaksefiskDB.colourMode == 0)
        blueBtn:SetChecked(LaksefiskDB.colourMode == 1)
    end
    UpdateRadios()

    redBtn:SetScript("OnClick", function()
        LaksefiskDB.colourMode = 0
        UpdateRadios()
    end)
    blueBtn:SetScript("OnClick", function()
        LaksefiskDB.colourMode = 1
        UpdateRadios()
    end)

    CreateSettingSlider(detectionTab, 0, -44, "Colour multiplier", "colourMult", 0, 15, 1,
        function(v) return string.format("%.1f", v * 0.2) end)

    CreateSettingSlider(detectionTab, 0, -88, "Colour closeness", "colourClose", 0, 15, 1,
        function(v) return string.format("%.1f", v * (5.0 / 15)) end)
```

- [ ] **Step 2: Add Move Bar button to General tab**

At the bottom of the General tab content (after the loot wait max slider), add:

```lua
    -- Move bar button at bottom of General tab
    local moveBarBtn = CreateFrame("Button", nil, generalTab, "UIPanelButtonTemplate")
    moveBarBtn:SetPoint("BOTTOMLEFT", 0, 4)
    moveBarBtn:SetSize(80, 22)
    moveBarBtn:SetText("Move Bar")
    moveBarBtn:SetScript("OnClick", function()
        SlashCmdList["LAKSEFISK"]("move")
    end)

    -- Reset defaults button
    local resetBtn = CreateFrame("Button", nil, generalTab, "UIPanelButtonTemplate")
    resetBtn:SetPoint("BOTTOMRIGHT", 0, 4)
    resetBtn:SetSize(90, 22)
    resetBtn:SetText("Reset Defaults")
    resetBtn:SetScript("OnClick", function()
        LaksefiskDB.stopFriendly = false
        LaksefiskDB.stopEnemy = false
        LaksefiskDB.stopBags = false
        LaksefiskDB.autoDelete = false
        LaksefiskDB.autoCalibrate = false
        LaksefiskDB.soundAlerts = false
        LaksefiskDB.colourMode = 0
        LaksefiskDB.castKeyIndex = 4
        LaksefiskDB.lureKeyIndex = 0
        LaksefiskDB.lootWaitMin = 3
        LaksefiskDB.lootWaitMax = 10
        LaksefiskDB.colourMult = 3
        LaksefiskDB.colourClose = 6
        -- Rebuild settings panel to reflect new values
        if settingsFrame then
            settingsFrame:Hide()
            settingsFrame = nil
            CreateSettingsPanel()
            activeTab = 1
            UpdateSettingsTabs()
            settingsFrame:Show()
        end
    end)
```

- [ ] **Step 3: Update help text to include new commands**

In the help section of the slash command handler, add:

```lua
        print("  /lf status  (toggle status bar)")
        print("  /lf settings  (toggle settings panel)")
```

- [ ] **Step 4: Commit**

```bash
git add addon/Laksefisk/Laksefisk.lua
git commit -m "feat: add Detection tab, move bar button, and reset defaults to settings panel"
```

---

### Task 11: Copy addon to WoW folder and manual testing

**Files:**
- `addon/Laksefisk/Laksefisk.lua` → WoW addon folder

- [ ] **Step 1: Copy addon to WoW folder**

```bash
cp -r C:/Users/perzi/laksefisk/addon/Laksefisk/* "/path/to/WoW/Interface/AddOns/Laksefisk/"
```

(Actual WoW path will need to be confirmed — check memory for previous addon copy commands)

- [ ] **Step 2: Manual test checklist**

1. `/reload` in WoW — verify "Laksefisk pixel bridge v9 loaded" message
2. Verify pixel bar has two rows visually (tiny, may need `/lf move` to see)
3. `/lf status` — verify status bar appears, shows "Idle", draggable
4. Start fishing — verify status bar updates to "Fishing", catch count increments
5. `/lf settings` — verify settings panel opens with 3 tabs
6. General tab: toggle checkboxes, change keys, adjust sliders
7. Lists tab: add/remove items from delete list and whitelist, toggle skip filters
8. Detection tab: switch colour mode, adjust sliders
9. Esc closes settings panel
10. Run the Python bot — verify it detects addon v2 (check log for addon_version=2)
11. Change a setting in WoW (e.g., toggle "stop on friendly") — verify bot picks it up
12. Swap back to old addon (no row 2) — verify bot falls back to local config

- [ ] **Step 3: Commit any fixes from testing**

```bash
git add -A
git commit -m "fix: adjustments from manual addon GUI testing"
```
