-- Laksefisk Pixel Bridge v9
-- Encodes game state as coloured pixels for the fishing bot to read.
-- Uses BINARY ONLY encoding (0 or 255 per channel) — completely immune to
-- WoW's gamma correction. Inspired by PixelMagic's proven approach.
--
-- Pixel layout (each pixel = 5x5 block, side by side):
--   [0]  Sync 1      — magenta (255, 0, 255)
--   [1]  Sync 2      — cyan (0, 255, 255)
--   [2]  Status      — R: alive(255)/dead(0)  G: combat(255)/not(0)  B: fishing(255)/not(0)
--   [3]  Counters    — R: loot_parity  G: bags_full(255)/ok(0)  B: cast_count_parity
--   [4]  Chat flags  — R: whisper_parity  G: say_parity  B: yell_parity
--   [5..7]  Catch count — 8 bits binary (0-255), MSB first — pixel 7 B = player nearby
--   [8..13]  Item ID — 18 bits binary (0-262143), MSB first across R,G,B
--   [14..16] Bait time — seconds/5 as 8-bit binary (0=no bait, 255=1275s max) — pixel 16 B = mouseover bobber
--   [17..19] Player HP — percent as 8-bit binary (0-100), pixel 19 B = junk on cursor
--   [20]  Enemy flag  — R:0  G:0  B: enemy_nearby(255)/not(0)
--
-- The pixel bar is placed at the bottom-centre of the screen.

local PIXEL_SIZE = 5
local PIXEL_GAP = 0
local PIXEL_STEP = PIXEL_SIZE + PIXEL_GAP
local NUM_PIXELS = 21       -- 0-7 control + 8-13 item ID + 14-16 bait + 17-19 hp + 20 enemy
local BAR_Y_OFFSET = 120
local ROW2_PIXELS = 13      -- settings pixels in row 2
local ITEM_ID_START = 8     -- first pixel index for item ID
local ITEM_ID_PIXELS = 6   -- 6 pixels × 3 bits = 18 bits
local BAIT_START = 14
local HP_START = 17

-- State
local lootCounter = 0
local castCounter = 0       -- total fishing casts
local whisperCounter = 0
local sayCounter = 0
local yellCounter = 0
local lastItemID = 0
local lastItemName = ""
local isDead = false
local isFishing = false
local playerNearby = false
local nearbyPlayers = {}     -- [name] = expiry time
local enemyNearby = false
local nearbyEnemies = {}     -- [name] = expiry time
local originalEnemyNP = nil       -- saved nameplateShowEnemies cvar
local originalEnemyNames = nil    -- saved UnitNameNPC cvar
local fishingSessionActive = false
local mouseoverBobber = false  -- true when GameTooltip shows "Fishing Bobber"
local junkOnCursor = false
local sessionStartTime = nil   -- GetTime() when first cast happened
local showStatusBar = false
local statusFrame = nil
local showSettingsPanel = false
local settingsFrame = nil
local activeTab = 1  -- 1=General, 2=Lists, 3=Detection
-- Known openable fishing containers (clams, trunks, crates, scrollcases)
local openableContainers = {
    [5523]  = true,  -- Small Barnacled Clam
    [5524]  = true,  -- Thick-shelled Clam
    [7973]  = true,  -- Big-mouth Clam
    [24476] = true,  -- Jaggal Clam
    [6357]  = true,  -- Sealed Crate
    [20708] = true,  -- Tightly Sealed Trunk
    [21113] = true,  -- Watertight Trunk
    [21150] = true,  -- Iron Bound Trunk
    [21228] = true,  -- Mithril Bound Trunk
    [13874] = true,  -- Heavy Crate
    [27513] = true,  -- Curious Crate
    [27481] = true,  -- Heavy Supply Crate
    [27511] = true,  -- Inscribed Scrollcase
}

-- Saved variables (persists across sessions via LaksefiskDB)
LaksefiskDB = LaksefiskDB or {}
local printNearby = false
local scanNameplates = true
local enforceNameplates = false

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

-- Pixel textures
local pixels = {}
local row2pixels = {}
local barFrame

---------------------------------------------------------------------------
-- Helpers
---------------------------------------------------------------------------

local function SetPixelRaw(index, r, g, b)
    if pixels[index] then
        pixels[index]:SetColorTexture(r / 255, g / 255, b / 255, 1)
    end
end

local function SetRow2PixelRaw(index, r, g, b)
    if row2pixels[index] then
        row2pixels[index]:SetColorTexture(r / 255, g / 255, b / 255, 1)
    end
end

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

local function Bit(value, pos)
    -- Returns 255 if bit at pos is set, 0 otherwise (pos 0 = LSB)
    return (math.floor(value / (2 ^ pos)) % 2 == 1) and 255 or 0
end

local function GetFreeBagSlots()
    local free = 0
    for bag = 0, 4 do
        local slots = C_Container and C_Container.GetContainerNumFreeSlots(bag)
                      or GetContainerNumFreeSlots(bag)
        free = free + (slots or 0)
    end
    return free
end

local function GetTotalBagSlots()
    local total = 0
    for bag = 0, 4 do
        local slots = C_Container and C_Container.GetContainerNumSlots(bag)
                      or GetContainerNumSlots(bag)
        total = total + (slots or 0)
    end
    return total
end

local function FormatDuration(seconds)
    if not seconds or seconds < 0 then return "0m" end
    local h = math.floor(seconds / 3600)
    local m = math.floor((seconds % 3600) / 60)
    if h > 0 then return string.format("%dh %dm", h, m) end
    return string.format("%dm", m)
end

local function EncodeItemID(itemID)
    -- Encode item ID as 18-bit binary across 6 pixels (MSB first, 3 bits per pixel)
    local id = math.min(itemID or 0, 262143)
    for i = 0, ITEM_ID_PIXELS - 1 do
        local bitPos = 17 - i * 3  -- MSB first: bits 17,16,15 then 14,13,12 etc.
        SetPixelRaw(ITEM_ID_START + i,
            Bit(id, bitPos),
            Bit(id, bitPos - 1),
            Bit(id, bitPos - 2)
        )
    end
end

---------------------------------------------------------------------------
-- Nearby player detection via friendly nameplates
---------------------------------------------------------------------------
local NEARBY_TIMEOUT = 10    -- seconds before a player is considered "gone"

local function EndFishingSession()
    if fishingSessionActive then
        if originalEnemyNP ~= nil then
            SetCVar("nameplateShowEnemies", originalEnemyNP)
        end
        if originalEnemyNames ~= nil then
            SetCVar("UnitNameNPC", originalEnemyNames)
        end
    end
    fishingSessionActive = false
    originalEnemyNP = nil
    originalEnemyNames = nil
    nearbyEnemies = {}
    enemyNearby = false
end

local function IsWhitelisted(unit, name)
    local db = LaksefiskDB or {}
    local lowerName = string.lower(name)
    -- Party/raid member
    if db.skipParty and (UnitInParty(unit) or UnitInRaid(unit)) then return true end
    -- Guild member
    if db.skipGuild and IsInGuild() then
        local numMembers = GetNumGuildMembers()
        for i = 1, numMembers do
            local gName = GetGuildRosterInfo(i)
            if gName then
                gName = string.match(gName, "^(.-)%-") or gName
                if string.lower(gName) == lowerName then return true end
            end
        end
    end
    -- Friends list
    if db.skipFriends then
        local numFriends = C_FriendList.GetNumFriends()
        for i = 1, numFriends do
            local info = C_FriendList.GetFriendInfoByIndex(i)
            if info and info.name and string.lower(info.name) == lowerName then return true end
        end
    end
    -- Custom whitelist
    if db.whitelist then
        for _, wName in ipairs(db.whitelist) do
            if string.lower(wName) == lowerName then return true end
        end
    end
    return false
end

local function ScanNearbyPlayers()
    if not scanNameplates then
        playerNearby = false
        enemyNearby = false
        return
    end

    -- Enforce friendly nameplates (if enabled)
    if enforceNameplates and GetCVar("nameplateShowFriends") ~= "1" then
        SetCVar("nameplateShowFriends", "1")
    end

    local now = GetTime()
    local plates = C_NamePlate.GetNamePlates()

    for _, plate in ipairs(plates) do
        local unit = plate.namePlateUnitToken
        if UnitExists(unit) and UnitIsPlayer(unit) and not UnitIsUnit(unit, "player") then
            local name = UnitName(unit)
            if name and not IsWhitelisted(unit, name) then
                if not UnitIsFriend("player", unit) then
                    if not nearbyEnemies[name] and printNearby then
                        print("|cff4FC3F7Laksefisk|r |cffFF3333enemy nearby:|r " .. name)
                    end
                    nearbyEnemies[name] = now + NEARBY_TIMEOUT
                else
                    if not nearbyPlayers[name] and printNearby then
                        print("|cff4FC3F7Laksefisk|r |cffFFCC00player nearby:|r " .. name)
                    end
                    nearbyPlayers[name] = now + NEARBY_TIMEOUT
                end
            end
        end
    end

    -- Expire old friendly entries
    local anyNearby = false
    for name, expiry in pairs(nearbyPlayers) do
        if now > expiry then
            nearbyPlayers[name] = nil
        else
            anyNearby = true
        end
    end
    playerNearby = anyNearby

    -- Expire old enemy entries
    enemyNearby = false
    for name, expiry in pairs(nearbyEnemies) do
        if now > expiry then
            nearbyEnemies[name] = nil
        else
            enemyNearby = true
        end
    end
end

local function CheckMouseoverBobber()
    -- Check if GameTooltip is showing "Fishing Bobber" (or localized equivalent)
    if GameTooltip:IsShown() then
        local text = GameTooltipTextLeft1 and GameTooltipTextLeft1:GetText()
        if text then
            local lower = string.lower(text)
            -- "Fishing Bobber" (EN), "Fiskesnøre" (NO), "Angelpose" (DE), etc.
            mouseoverBobber = (lower == "fishing bobber" or lower == "fiskesnøre"
                               or lower == "flotteur" or lower == "angelpose"
                               or lower == "bobber de pesca")
            return
        end
    end
    mouseoverBobber = false
end

local function UpdateAllPixels()
    -- [0] Sync 1 — magenta
    SetPixelRaw(0, 255, 0, 255)

    -- [1] Sync 2 — cyan
    SetPixelRaw(1, 0, 255, 255)

    -- [2] Status
    SetPixelRaw(2,
        isDead and 0 or 255,
        UnitAffectingCombat("player") and 255 or 0,
        isFishing and 255 or 0
    )

    -- [3] Counters: loot parity, bags full, cast parity
    local bagsFull = (GetFreeBagSlots() <= 2) and 255 or 0
    SetPixelRaw(3,
        (lootCounter % 2 == 1) and 255 or 0,
        bagsFull,
        (castCounter % 2 == 1) and 255 or 0
    )

    -- [4] Chat parity
    SetPixelRaw(4,
        (whisperCounter % 2 == 1) and 255 or 0,
        (sayCounter % 2 == 1) and 255 or 0,
        (yellCounter % 2 == 1) and 255 or 0
    )

    -- [5..7] Catch count as 8-bit binary (MSB first, 3 bits per pixel)
    -- Pixel 7 blue = player nearby flag
    local count = math.min(lootCounter, 255)
    SetPixelRaw(5, Bit(count, 7), Bit(count, 6), Bit(count, 5))
    SetPixelRaw(6, Bit(count, 4), Bit(count, 3), Bit(count, 2))
    SetPixelRaw(7, Bit(count, 1), Bit(count, 0), playerNearby and 255 or 0)

    -- [8..13] Item ID as 18-bit binary (MSB first)
    EncodeItemID(lastItemID)

    -- [14..16] Bait remaining time as 8-bit binary (seconds/5, MSB first)
    local baitVal = 0
    local hasEnchant, expiry = GetWeaponEnchantInfo()
    if hasEnchant and expiry and expiry > 0 then
        baitVal = math.min(math.floor(expiry / 5000), 255)
    end
    SetPixelRaw(BAIT_START, Bit(baitVal, 7), Bit(baitVal, 6), Bit(baitVal, 5))
    SetPixelRaw(BAIT_START + 1, Bit(baitVal, 4), Bit(baitVal, 3), Bit(baitVal, 2))
    SetPixelRaw(BAIT_START + 2, Bit(baitVal, 1), Bit(baitVal, 0), mouseoverBobber and 255 or 0)

    -- [17..19] Player HP percent as 8-bit binary (MSB first)
    local hp = 0
    local maxHp = UnitHealthMax("player")
    if maxHp > 0 then
        hp = math.floor(UnitHealth("player") / maxHp * 100 + 0.5)
    end
    hp = math.min(hp, 255)
    SetPixelRaw(HP_START, Bit(hp, 7), Bit(hp, 6), Bit(hp, 5))
    SetPixelRaw(HP_START + 1, Bit(hp, 4), Bit(hp, 3), Bit(hp, 2))
    -- Auto-recover if cursor cleared (deleted or cancelled)
    if junkOnCursor and not CursorHasItem() then
        junkOnCursor = false
        if LaksefiskDB.debugDelete then
            print("|cff4FC3F7Laksefisk|r |cff66FF66junk deleted|r")
        end
    end

    -- Pixel 19: R = HP bit 1, G = HP bit 0, B = junk on cursor
    SetPixelRaw(HP_START + 2, Bit(hp, 1), Bit(hp, 0), junkOnCursor and 255 or 0)

    -- [20] Enemy nearby flag
    SetPixelRaw(20, 0, 0, enemyNearby and 255 or 0)

end

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
        Bit(db.colourMode, 0),
        db.skipParty and 255 or 0,
        db.skipGuild and 255 or 0
    )

    -- [25-26] skip_friends + cast_key (5-bit) (indices 4-5)
    -- Pixel 25: R=skip_friends, G=castKey[4], B=castKey[3]
    local ck = math.min(db.castKeyIndex or 0, 31)
    SetRow2PixelRaw(4,
        db.skipFriends and 255 or 0,
        Bit(ck, 4),
        Bit(ck, 3)
    )
    -- Pixel 26: R=castKey[2], G=castKey[1], B=castKey[0]
    SetRow2PixelRaw(5, Bit(ck, 2), Bit(ck, 1), Bit(ck, 0))

    -- [27-28] lure_key (5-bit) (indices 6-7)
    local lk = math.min(db.lureKeyIndex or 0, 31)
    -- Pixel 27: R=lureKey[4], G=lureKey[3], B=lureKey[2]
    SetRow2PixelRaw(6, Bit(lk, 4), Bit(lk, 3), Bit(lk, 2))
    -- Pixel 28: R=lureKey[1], G=lureKey[0], B=waitMin[3]
    local wmin = math.min(db.lootWaitMin or 0, 15)
    SetRow2PixelRaw(7, Bit(lk, 1), Bit(lk, 0), Bit(wmin, 3))

    -- [29] wait_min bits 2,1,0 (index 8)
    SetRow2PixelRaw(8, Bit(wmin, 2), Bit(wmin, 1), Bit(wmin, 0))

    -- [30] wait_max bits 3,2,1 (index 9)
    local wmax = math.min(db.lootWaitMax or 0, 15)
    SetRow2PixelRaw(9, Bit(wmax, 3), Bit(wmax, 2), Bit(wmax, 1))

    -- [31] wait_max[0], col_mult[3], col_mult[2] (index 10)
    local cm = math.min(db.colourMult or 0, 15)
    SetRow2PixelRaw(10, Bit(wmax, 0), Bit(cm, 3), Bit(cm, 2))

    -- [32] col_mult[1], col_mult[0], col_close[3] (index 11)
    local cc = math.min(db.colourClose or 0, 15)
    SetRow2PixelRaw(11, Bit(cm, 1), Bit(cm, 0), Bit(cc, 3))

    -- [33] col_close[2], col_close[1], col_close[0] (index 12)
    SetRow2PixelRaw(12, Bit(cc, 2), Bit(cc, 1), Bit(cc, 0))
end

---------------------------------------------------------------------------
-- Auto-delete junk fish
---------------------------------------------------------------------------

local function ShouldDelete(itemName)
    if not LaksefiskDB.deleteList then return false end
    local lower = string.lower(itemName)
    for _, name in ipairs(LaksefiskDB.deleteList) do
        if string.lower(name) == lower then
            return true
        end
    end
    return false
end

local function DeleteFromBags(itemName)
    -- Find and delete item from bags
    for bag = 0, 4 do
        local numSlots = C_Container and C_Container.GetContainerNumSlots(bag)
                         or GetContainerNumSlots(bag)
        for slot = 1, (numSlots or 0) do
            local info
            if C_Container and C_Container.GetContainerItemInfo then
                info = C_Container.GetContainerItemInfo(bag, slot)
            else
                local _, count, _, _, _, _, link = GetContainerItemInfo(bag, slot)
                if link then
                    info = { hyperlink = link, stackCount = count }
                end
            end
            if info and info.hyperlink then
                local name = GetItemInfo(info.hyperlink)
                if name and string.lower(name) == string.lower(itemName) then
                    if C_Container and C_Container.PickupContainerItem then
                        C_Container.PickupContainerItem(bag, slot)
                    else
                        PickupContainerItem(bag, slot)
                    end
                    -- Item is now on cursor — show destroy popup for bot to confirm
                    junkOnCursor = true
                    if LaksefiskDB.debugDelete then
                        print("|cff4FC3F7Laksefisk|r |cffFFFF00picked up junk|r " .. itemName)
                    end
                    -- Show the DELETE_ITEM popup (not protected); bot will hardware-click the Yes button
                    local link = info.hyperlink
                    C_Timer.After(0.1, function()
                        if junkOnCursor and CursorHasItem() then
                            StaticPopup_Show("DELETE_ITEM", link)
                        end
                    end)
                    return true
                end
            end
        end
    end
    return false
end

---------------------------------------------------------------------------
-- Auto-open containers (clams, trunks, crates)
---------------------------------------------------------------------------

local function OpenContainerFromBags(targetID)
    if InCombatLockdown() then return end
    if GetFreeBagSlots() <= 2 then return end  -- don't open if bags nearly full
    for bag = 0, 4 do
        local numSlots = C_Container and C_Container.GetContainerNumSlots(bag)
                         or GetContainerNumSlots(bag)
        for slot = 1, (numSlots or 0) do
            local itemID = C_Container and C_Container.GetContainerItemID(bag, slot)
                           or GetContainerItemID(bag, slot)
            if itemID and itemID == targetID then
                if C_Container and C_Container.UseContainerItem then
                    C_Container.UseContainerItem(bag, slot)
                else
                    UseContainerItem(bag, slot)
                end
                return true
            end
        end
    end
    return false
end

local function OpenAllContainers()
    if InCombatLockdown() then return 0 end
    if GetFreeBagSlots() <= 2 then return 0 end
    local opened = 0
    for bag = 0, 4 do
        local numSlots = C_Container and C_Container.GetContainerNumSlots(bag)
                         or GetContainerNumSlots(bag)
        for slot = 1, (numSlots or 0) do
            local itemID = C_Container and C_Container.GetContainerItemID(bag, slot)
                           or GetContainerItemID(bag, slot)
            if itemID and openableContainers[itemID] then
                C_Timer.After(opened * 0.8, function()
                    if not InCombatLockdown() and GetFreeBagSlots() > 2 then
                        if C_Container and C_Container.UseContainerItem then
                            C_Container.UseContainerItem(bag, slot)
                        else
                            UseContainerItem(bag, slot)
                        end
                    end
                end)
                opened = opened + 1
            end
        end
    end
    return opened
end

-- Debug log when destroy popup appears for junk deletion
hooksecurefunc("StaticPopup_Show", function(which)
    if junkOnCursor and (which == "DELETE_ITEM" or which == "DELETE_GOOD_ITEM") then
        if LaksefiskDB.debugDelete then
            print("|cff4FC3F7Laksefisk|r |cffFFFF00destroy popup shown — bot will press F12|r")
        end
    end
end)

---------------------------------------------------------------------------
-- Settings panel GUI
---------------------------------------------------------------------------

local function CreateCheckbox(parent, x, y, label, dbKey, onChange, tooltip)
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
    if tooltip then AddTooltip(cb, label, tooltip) end
    return cb
end

local function CreateSettingSlider(parent, x, y, label, dbKey, minVal, maxVal, step, displayFn, tooltip)
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
        val = math.floor(val / step + 0.5) * step
        LaksefiskDB[dbKey] = val
        updateText()
    end)

    container.slider = slider
    container.dbKey = dbKey
    if tooltip then AddTooltip(container, label, tooltip) end
    return container
end

local function CreateKeyCaptureButton(parent, x, y, label, dbKey, tooltip)
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
            local curIdx = LaksefiskDB[dbKey] or 0
            btn:SetText(KEY_INDEX_TO_NAME[curIdx] or "None")
            return
        end
        local keyIdx = KEY_NAME_TO_INDEX[key]
        if keyIdx then
            LaksefiskDB[dbKey] = keyIdx
            btn:SetText(KEY_INDEX_TO_NAME[keyIdx] or key)
        else
            local curIdx = LaksefiskDB[dbKey] or 0
            btn:SetText(KEY_INDEX_TO_NAME[curIdx] or "None")
        end
    end)
    btn:EnableKeyboard(true)

    container.btn = btn
    container.dbKey = dbKey
    if tooltip then AddTooltip(container, label, tooltip) end
    return container
end

local UpdateSettingsTabs  -- forward declaration
local generalTab, listsTab, detectionTab  -- tab content frames

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

    tinsert(UISpecialFrames, "LaksefiskSettings")

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

    local title = settingsFrame:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", 10, -8)
    title:SetText("|cffffd100Laksefisk Settings|r")

    local closeBtn = CreateFrame("Button", nil, settingsFrame, "UIPanelCloseButton")
    closeBtn:SetPoint("TOPRIGHT", -2, -2)
    closeBtn:SetScript("OnClick", function()
        showSettingsPanel = false
        settingsFrame:Hide()
    end)

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

    local contentArea = CreateFrame("Frame", nil, settingsFrame)
    contentArea:SetPoint("TOPLEFT", 8, -54)
    contentArea:SetPoint("BOTTOMRIGHT", -8, 8)

    generalTab = CreateFrame("Frame", nil, contentArea)
    generalTab:SetAllPoints()

    local yOff = 0
    local sectionLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    sectionLabel:SetPoint("TOPLEFT", 0, yOff)
    sectionLabel:SetText("|cffff8000STOP CONDITIONS|r")
    yOff = yOff - 16

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
    yOff = yOff - 28

    local keysLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    keysLabel:SetPoint("TOPLEFT", 0, yOff)
    keysLabel:SetText("|cffff8000KEYS|r")
    yOff = yOff - 16

    CreateKeyCaptureButton(generalTab, 0, yOff, "Cast key", "castKeyIndex",
        "Click then press a key to set the cast keybind")
    yOff = yOff - 24
    CreateKeyCaptureButton(generalTab, 0, yOff, "Lure key", "lureKeyIndex",
        "Click then press a key to set the lure keybind")
    yOff = yOff - 32

    local timingLabel = generalTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    timingLabel:SetPoint("TOPLEFT", 0, yOff)
    timingLabel:SetText("|cffff8000TIMING|r")
    yOff = yOff - 16

    CreateSettingSlider(generalTab, 0, yOff, "Loot wait min", "lootWaitMin", 0, 15, 1,
        function(v) return string.format("%.1fs", v * 0.2) end,
        "Minimum random delay before looting")
    yOff = yOff - 40
    CreateSettingSlider(generalTab, 0, yOff, "Loot wait max", "lootWaitMax", 0, 15, 1,
        function(v) return string.format("%.1fs", v * 0.2) end,
        "Maximum random delay before looting")

    -- Move bar button at bottom of General tab
    local moveBarBtn = CreateFrame("Button", nil, generalTab, "UIPanelButtonTemplate")
    moveBarBtn:SetPoint("BOTTOMLEFT", 0, 4)
    moveBarBtn:SetSize(80, 22)
    moveBarBtn:SetText("Move Bar")
    moveBarBtn:SetScript("OnClick", function()
        SlashCmdList["LAKSEFISK"]("move")
    end)
    AddTooltip(moveBarBtn, "Move Bar", "Drag the pixel bar to a new position")

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
    AddTooltip(resetBtn, "Reset Defaults", "Reset all settings to defaults")

    -- Lists tab content
    listsTab = CreateFrame("Frame", nil, contentArea)
    listsTab:SetAllPoints()

    CreateEditableList(listsTab, 0, 0, 100, "AUTO-DELETE LIST", "deleteList")
    CreateEditableList(listsTab, 0, -106, 90, "PLAYER WHITELIST", "whitelist")

    local skipLabel = listsTab:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    skipLabel:SetPoint("TOPLEFT", 0, -202)
    skipLabel:SetText("|cffff8000AUTO-SKIP (don't pause for)|r")

    CreateCheckbox(listsTab, 0, -218, "Party members", "skipParty", nil,
        "Don't pause for party members")
    CreateCheckbox(listsTab, 0, -240, "Guild members", "skipGuild", nil,
        "Don't pause for guild members")
    CreateCheckbox(listsTab, 0, -262, "Friends list", "skipFriends", nil,
        "Don't pause for players on your friends list")

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
    AddTooltip(redBtn, "Red", "Red for standard bobbers")
    AddTooltip(blueBtn, "Blue", "Blue for special/blue bobbers")

    CreateSettingSlider(detectionTab, 0, -44, "Colour multiplier", "colourMult", 0, 15, 1,
        function(v) return string.format("%.1f", v * 0.2) end,
        "Scales bobber colour detection range")

    CreateSettingSlider(detectionTab, 0, -88, "Colour closeness", "colourClose", 0, 15, 1,
        function(v) return string.format("%.1f", v * (5.0 / 15)) end,
        "How close a pixel must match the target bobber colour")

    settingsFrame:Hide()

    local saved = LaksefiskDB.settingsPos
    if saved and saved.x and saved.y then
        settingsFrame:ClearAllPoints()
        settingsFrame:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", saved.x, saved.y)
    end
end

UpdateSettingsTabs = function()
    if not settingsFrame then return end
    if generalTab then generalTab:SetShown(activeTab == 1) end
    if listsTab then listsTab:SetShown(activeTab == 2) end
    if detectionTab then detectionTab:SetShown(activeTab == 3) end
end

---------------------------------------------------------------------------
-- Status bar GUI
---------------------------------------------------------------------------

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
    AddTooltip(statusFrame, "Laksefisk", "Drag to move. /lf status to toggle")

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

---------------------------------------------------------------------------
-- Create the pixel bar
---------------------------------------------------------------------------

local barMovable = false

local function CreatePixelBar()
    local totalW = NUM_PIXELS * PIXEL_STEP
    local startX = (GetScreenWidth() - totalW) / 2

    barFrame = CreateFrame("Frame", "LaksefiskBar", UIParent)
    barFrame:SetSize(totalW, PIXEL_SIZE * 2)

    -- Restore saved position or use default
    local saved = LaksefiskDB.barPos
    if saved and saved.x and saved.y and saved.x >= 0 and saved.y >= 0
       and saved.x < GetScreenWidth() and saved.y < GetScreenHeight() then
        barFrame:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", saved.x, saved.y)
    else
        LaksefiskDB.barPos = nil
        barFrame:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", startX, BAR_Y_OFFSET)
    end
    barFrame:SetFrameStrata("TOOLTIP")

    -- Dragging support (only active when unlocked via /lf move)
    barFrame:SetMovable(true)
    barFrame:EnableMouse(false)
    barFrame:RegisterForDrag("LeftButton")
    barFrame:SetScript("OnDragStart", function(self)
        if barMovable then self:StartMoving() end
    end)
    barFrame:SetScript("OnDragStop", function(self)
        self:StopMovingOrSizing()
        local x = self:GetLeft()
        local y = self:GetBottom()
        if x and y then
            LaksefiskDB.barPos = { x = x, y = y }
            self:ClearAllPoints()
            self:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", x, y)
        end
    end)

    local bg = barFrame:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints()
    bg:SetColorTexture(0, 0, 0, 1)

    for i = 0, NUM_PIXELS - 1 do
        local px = barFrame:CreateTexture(nil, "OVERLAY")
        px:SetSize(PIXEL_SIZE, PIXEL_SIZE)
        px:SetPoint("TOPLEFT", barFrame, "TOPLEFT", i * PIXEL_STEP, 0)
        px:SetColorTexture(0, 0, 0, 1)
        pixels[i] = px
    end

    -- Row 2: settings pixels (below row 1)
    for i = 0, ROW2_PIXELS - 1 do
        local px = barFrame:CreateTexture(nil, "OVERLAY")
        px:SetSize(PIXEL_SIZE, PIXEL_SIZE)
        px:SetPoint("TOPLEFT", barFrame, "TOPLEFT", i * PIXEL_STEP, -PIXEL_SIZE)
        px:SetColorTexture(0, 0, 0, 1)
        row2pixels[i] = px
    end

    SetPixelRaw(0, 255, 0, 255)
    SetPixelRaw(1, 0, 255, 255)
    EncodeItemID(0)

    -- Permanently bind F12 to click the destroy popup confirm button.
    -- Harmless when no popup is showing (button not visible = no-op).
    SetOverrideBindingClick(barFrame, true, "F12", "StaticPopup1Button1")

end

---------------------------------------------------------------------------
-- Event handling
---------------------------------------------------------------------------

local eventFrame = CreateFrame("Frame")
eventFrame:RegisterEvent("PLAYER_LOGIN")
eventFrame:RegisterEvent("PLAYER_DEAD")
eventFrame:RegisterEvent("PLAYER_ALIVE")
eventFrame:RegisterEvent("PLAYER_UNGHOST")
eventFrame:RegisterEvent("CHAT_MSG_LOOT")
eventFrame:RegisterEvent("CHAT_MSG_WHISPER")
eventFrame:RegisterEvent("CHAT_MSG_SAY")
eventFrame:RegisterEvent("CHAT_MSG_YELL")
eventFrame:RegisterEvent("UNIT_SPELLCAST_CHANNEL_START")
eventFrame:RegisterEvent("UNIT_SPELLCAST_CHANNEL_STOP")
eventFrame:RegisterEvent("PLAYER_REGEN_DISABLED")
eventFrame:RegisterEvent("PLAYER_LEAVING_WORLD")

eventFrame:SetScript("OnEvent", function(self, event, ...)
    if event == "PLAYER_LOGIN" then
        LaksefiskDB = LaksefiskDB or {}
        LaksefiskDB.deleteList = LaksefiskDB.deleteList or {}
        LaksefiskDB.debugDelete = LaksefiskDB.debugDelete or false
        if LaksefiskDB.autoOpenContainers == nil then LaksefiskDB.autoOpenContainers = true end
        LaksefiskDB.whitelist = LaksefiskDB.whitelist or {}
        if LaksefiskDB.skipParty == nil then LaksefiskDB.skipParty = false end
        if LaksefiskDB.skipGuild == nil then LaksefiskDB.skipGuild = false end
        if LaksefiskDB.skipFriends == nil then LaksefiskDB.skipFriends = false end
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
        CreatePixelBar()
        CreateStatusBar()
        -- Restore status bar visibility
        if LaksefiskDB.showStatusBar then
            showStatusBar = true
            if statusFrame then statusFrame:Show() end
        end
        CreateSettingsPanel()
        activeTab = LaksefiskDB.activeTab or 1
        UpdateSettingsTabs()
        local nDel = #LaksefiskDB.deleteList
        local cStr = LaksefiskDB.autoOpenContainers and "ON" or "OFF"
        print("|cff4FC3F7Laksefisk|r pixel bridge v9 loaded (" .. NUM_PIXELS .. "+" .. ROW2_PIXELS .. " pixels, " .. nDel .. " auto-delete, containers " .. cStr .. ")")

    elseif event == "PLAYER_DEAD" then
        isDead = true

    elseif event == "PLAYER_ALIVE" or event == "PLAYER_UNGHOST" then
        isDead = false
        EndFishingSession()

    elseif event == "CHAT_MSG_LOOT" then
        local msg = ...
        local itemName = string.match(msg, "%[(.-)%]")
        local itemID = tonumber(string.match(msg, "item:(%d+)"))
        if itemName then
            lastItemName = itemName
            lastItemID = itemID or 0
            lootCounter = (lootCounter % 255) + 1
            -- Auto-open if it's a known container (clams, trunks, crates)
            if LaksefiskDB.autoOpenContainers and itemID and openableContainers[itemID] then
                C_Timer.After(0.5, function()
                    OpenContainerFromBags(itemID)
                end)
            end
            -- Auto-delete if on the junk list
            if ShouldDelete(itemName) then
                -- Small delay to let the item land in bags
                C_Timer.After(0.5, function()
                    DeleteFromBags(itemName)
                end)
            end
        end

    elseif event == "CHAT_MSG_WHISPER" then
        whisperCounter = (whisperCounter % 255) + 1

    elseif event == "CHAT_MSG_SAY" then
        sayCounter = (sayCounter % 255) + 1

    elseif event == "CHAT_MSG_YELL" then
        yellCounter = (yellCounter % 255) + 1

    elseif event == "UNIT_SPELLCAST_CHANNEL_START" then
        local unit, _, spellID = ...
        if unit == "player" and spellID then
            local name = GetSpellInfo(spellID)
            if name and (name == "Fishing" or name == "Fiske") then
                isFishing = true
                castCounter = castCounter + 1
                if not sessionStartTime then
                    sessionStartTime = GetTime()
                end
                -- Save original settings on first cast
                if not fishingSessionActive then
                    originalEnemyNP = GetCVar("nameplateShowEnemies")
                    originalEnemyNames = GetCVar("UnitNameNPC")
                    fishingSessionActive = true
                end
                -- Disable enemy nameplates and NPC names during bobber watching
                SetCVar("nameplateShowEnemies", "0")
                SetCVar("UnitNameNPC", "0")
            end
        end

    elseif event == "UNIT_SPELLCAST_CHANNEL_STOP" then
        local unit = ...
        if unit == "player" then
            isFishing = false
            -- Restore NPC names between casts (next cast will turn them off again)
            if fishingSessionActive and originalEnemyNames ~= nil then
                SetCVar("UnitNameNPC", originalEnemyNames)
            end
            -- Briefly enable enemy nameplates for scan, then disable again
            if fishingSessionActive then
                SetCVar("nameplateShowEnemies", "1")
                C_Timer.After(0.3, function()
                    ScanNearbyPlayers()
                    if fishingSessionActive then
                        SetCVar("nameplateShowEnemies", "0")
                    end
                end)
            end
        end

    elseif event == "PLAYER_REGEN_DISABLED" then
        -- Entered combat — end fishing session, restore nameplates
        EndFishingSession()

    elseif event == "PLAYER_LEAVING_WORLD" then
        -- Logout, /reload, disconnect — restore nameplates
        EndFishingSession()

    end
end)

---------------------------------------------------------------------------
-- OnUpdate
---------------------------------------------------------------------------

local updateFrame = CreateFrame("Frame")
local elapsed = 0
local scanElapsed = 0
updateFrame:SetScript("OnUpdate", function(self, dt)
    elapsed = elapsed + dt
    scanElapsed = scanElapsed + dt
    if elapsed >= 0.05 then
        elapsed = 0
        CheckMouseoverBobber()
        if barFrame then
            UpdateAllPixels()
            UpdateRow2Pixels()
            UpdateStatusBar()
        end
    end
    if scanElapsed >= 1.0 then
        scanElapsed = 0
        ScanNearbyPlayers()
    end
end)

---------------------------------------------------------------------------
-- Slash commands
---------------------------------------------------------------------------

SLASH_LAKSEFISK1 = "/laksefisk"
SLASH_LAKSEFISK2 = "/lf"
SlashCmdList["LAKSEFISK"] = function(msg)
    local cmd = string.lower(msg or "")

    if cmd == "hide" then
        barFrame:Hide()
        print("|cff4FC3F7Laksefisk|r pixels hidden")

    elseif cmd == "show" then
        barFrame:Show()
        print("|cff4FC3F7Laksefisk|r pixels visible")

    elseif cmd == "debug" then
        print("|cff4FC3F7Laksefisk|r debug:")
        print("  Dead: " .. tostring(isDead))
        print("  Fishing: " .. tostring(isFishing))
        print("  Loot counter: " .. lootCounter)
        print("  Cast counter: " .. castCounter)
        local hasEnchant, expiry = GetWeaponEnchantInfo()
        if hasEnchant and expiry then
            print("  Bait: active (" .. math.floor(expiry / 1000) .. "s remaining)")
        else
            print("  Bait: none")
        end
        local maxHp = UnitHealthMax("player")
        local hpPct = maxHp > 0 and math.floor(UnitHealth("player") / maxHp * 100 + 0.5) or 0
        print("  HP: " .. hpPct .. "%")
        print("  Last item: " .. (lastItemName ~= "" and lastItemName or "(none)") .. " (ID: " .. lastItemID .. ")")
        print("  Free bag slots: " .. GetFreeBagSlots())
        print("  Whispers: " .. whisperCounter)
        print("  Says: " .. sayCounter)
        print("  Yells: " .. yellCounter)
        print("  Player nearby: " .. tostring(playerNearby))
        local nCount = 0
        for name, _ in pairs(nearbyPlayers) do
            print("    - |cffFFCC00" .. name .. "|r")
            nCount = nCount + 1
        end
        if nCount == 0 then print("    (none)") end
        print("  Enemy nearby: " .. tostring(enemyNearby))
        local eCount = 0
        for name, _ in pairs(nearbyEnemies) do
            print("    - |cffFF3333" .. name .. "|r")
            eCount = eCount + 1
        end
        if eCount == 0 then print("    (none)") end
        print("  Fishing session: " .. tostring(fishingSessionActive))
        print("  Saved enemy NP cvar: " .. tostring(originalEnemyNP))
        print("  Saved enemy names cvar: " .. tostring(originalEnemyNames))
        print("  Auto-delete list: " .. #(LaksefiskDB.deleteList or {}))

    elseif cmd == "test" then
        lastItemName = "Raw Bristle Whisker Catfish"
        lastItemID = 6308
        lootCounter = (lootCounter % 255) + 1
        print("|cff4FC3F7Laksefisk|r test loot: " .. lastItemName .. " ID:" .. lastItemID .. " (count=" .. lootCounter .. ")")

    elseif cmd == "test2" then
        lastItemName = "Oily Blackmouth"
        lastItemID = 6358
        lootCounter = (lootCounter % 255) + 1
        print("|cff4FC3F7Laksefisk|r test loot: " .. lastItemName .. " ID:" .. lastItemID .. " (count=" .. lootCounter .. ")")

    elseif cmd == "test3" then
        lastItemName = "Nat's Lucky Fishing Pole"
        lastItemID = 19979
        lootCounter = (lootCounter % 255) + 1
        print("|cff4FC3F7Laksefisk|r test loot: " .. lastItemName .. " ID:" .. lastItemID .. " (count=" .. lootCounter .. ")")

    elseif cmd == "whisper" then
        whisperCounter = (whisperCounter % 255) + 1
        print("|cff4FC3F7Laksefisk|r fake whisper (" .. whisperCounter .. ")")

    elseif cmd == "say" then
        sayCounter = (sayCounter % 255) + 1
        print("|cff4FC3F7Laksefisk|r fake say (" .. sayCounter .. ")")

    elseif cmd == "yell" then
        yellCounter = (yellCounter % 255) + 1
        print("|cff4FC3F7Laksefisk|r fake yell (" .. yellCounter .. ")")

    elseif cmd == "nearby" then
        printNearby = not printNearby
        print("|cff4FC3F7Laksefisk|r nearby chat alerts: " .. (printNearby and "ON" or "OFF"))

    elseif cmd == "nameplates" then
        enforceNameplates = not enforceNameplates
        print("|cff4FC3F7Laksefisk|r auto-enable friendly nameplates: " .. (enforceNameplates and "ON" or "OFF"))

    elseif cmd == "dead" then
        isDead = not isDead
        print("|cff4FC3F7Laksefisk|r dead=" .. tostring(isDead))

    elseif string.sub(cmd, 1, 10) == "delete add" then
        local item = string.match(msg, "delete add (.+)")
        if item and item ~= "" then
            -- Strip item link to plain name: [Name] or |c...|Hitem:...|h[Name]|h|r → Name
            item = string.match(item, "%[(.-)%]") or item
            table.insert(LaksefiskDB.deleteList, item)
            print("|cff4FC3F7Laksefisk|r added to delete list: |cffFF6666" .. item .. "|r")
            print("  Total: " .. #LaksefiskDB.deleteList .. " items")
        else
            print("|cff4FC3F7Laksefisk|r usage: /lf delete add Item Name")
        end

    elseif string.sub(cmd, 1, 13) == "delete remove" then
        local item = string.match(msg, "delete remove (.+)")
        if item then
            -- Strip item link to plain name: [Name] or |c...|Hitem:...|h[Name]|h|r → Name
            item = string.match(item, "%[(.-)%]") or item
            local lower = string.lower(item)
            for i, name in ipairs(LaksefiskDB.deleteList) do
                if string.lower(name) == lower then
                    table.remove(LaksefiskDB.deleteList, i)
                    print("|cff4FC3F7Laksefisk|r removed: " .. name)
                    return
                end
            end
            print("|cff4FC3F7Laksefisk|r not found: " .. item)
        end

    elseif cmd == "delete list" then
        if #LaksefiskDB.deleteList == 0 then
            print("|cff4FC3F7Laksefisk|r delete list is empty")
        else
            print("|cff4FC3F7Laksefisk|r auto-delete list:")
            for i, name in ipairs(LaksefiskDB.deleteList) do
                print("  " .. i .. ". |cffFF6666" .. name .. "|r")
            end
        end

    elseif cmd == "delete clear" then
        LaksefiskDB.deleteList = {}
        print("|cff4FC3F7Laksefisk|r delete list cleared")

    elseif cmd == "delete debug" then
        LaksefiskDB.debugDelete = not LaksefiskDB.debugDelete
        print("|cff4FC3F7Laksefisk|r delete debug: " .. (LaksefiskDB.debugDelete and "ON" or "OFF"))

    elseif string.sub(cmd, 1, 13) == "whitelist add" then
        local name = string.match(msg, "whitelist add (.+)")
        if name and name ~= "" then
            name = string.match(name, "%[(.-)%]") or name
            name = name:gsub("^%s+", ""):gsub("%s+$", "")
            LaksefiskDB.whitelist = LaksefiskDB.whitelist or {}
            table.insert(LaksefiskDB.whitelist, name)
            print("|cff4FC3F7Laksefisk|r whitelist added: |cff66FF66" .. name .. "|r")
        else
            print("|cff4FC3F7Laksefisk|r usage: /lf whitelist add Player Name")
        end

    elseif string.sub(cmd, 1, 16) == "whitelist remove" then
        local name = string.match(msg, "whitelist remove (.+)")
        if name then
            name = string.match(name, "%[(.-)%]") or name
            name = name:gsub("^%s+", ""):gsub("%s+$", "")
            local lower = string.lower(name)
            LaksefiskDB.whitelist = LaksefiskDB.whitelist or {}
            for i, wName in ipairs(LaksefiskDB.whitelist) do
                if string.lower(wName) == lower then
                    table.remove(LaksefiskDB.whitelist, i)
                    print("|cff4FC3F7Laksefisk|r whitelist removed: " .. wName)
                    return
                end
            end
            print("|cff4FC3F7Laksefisk|r not found: " .. name)
        end

    elseif cmd == "whitelist list" then
        LaksefiskDB.whitelist = LaksefiskDB.whitelist or {}
        if #LaksefiskDB.whitelist == 0 then
            print("|cff4FC3F7Laksefisk|r whitelist is empty (guild/party/friends auto-skipped)")
        else
            print("|cff4FC3F7Laksefisk|r whitelist:")
            for i, name in ipairs(LaksefiskDB.whitelist) do
                print("  " .. i .. ". |cff66FF66" .. name .. "|r")
            end
            print("  (guild/party/friends also auto-skipped)")
        end

    elseif cmd == "whitelist clear" then
        LaksefiskDB.whitelist = {}
        print("|cff4FC3F7Laksefisk|r whitelist cleared")

    elseif cmd == "skip party" then
        LaksefiskDB.skipParty = not LaksefiskDB.skipParty
        print("|cff4FC3F7Laksefisk|r skip party/raid: " .. (LaksefiskDB.skipParty and "|cff66FF66ON|r" or "|cffFF6666OFF|r"))

    elseif cmd == "skip guild" then
        LaksefiskDB.skipGuild = not LaksefiskDB.skipGuild
        print("|cff4FC3F7Laksefisk|r skip guild: " .. (LaksefiskDB.skipGuild and "|cff66FF66ON|r" or "|cffFF6666OFF|r"))

    elseif cmd == "skip friends" then
        LaksefiskDB.skipFriends = not LaksefiskDB.skipFriends
        print("|cff4FC3F7Laksefisk|r skip friends: " .. (LaksefiskDB.skipFriends and "|cff66FF66ON|r" or "|cffFF6666OFF|r"))

    elseif cmd == "move" then
        barMovable = not barMovable
        barFrame:EnableMouse(barMovable)
        if barMovable then
            -- Make bar bigger and visible while moving
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, PIXEL_SIZE * 2 + 10)
            print("|cff4FC3F7Laksefisk|r pixel bar |cff66FF66UNLOCKED|r — drag to move, then /lf move to lock")
        else
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, PIXEL_SIZE * 2)
            print("|cff4FC3F7Laksefisk|r pixel bar |cffFF6666LOCKED|r")
        end

    elseif cmd == "open" then
        local n = OpenAllContainers()
        if n > 0 then
            print("|cff4FC3F7Laksefisk|r opening " .. n .. " container(s)...")
        else
            print("|cff4FC3F7Laksefisk|r no openable containers found in bags")
        end

    elseif cmd == "containers" then
        LaksefiskDB.autoOpenContainers = not LaksefiskDB.autoOpenContainers
        local state = LaksefiskDB.autoOpenContainers and "|cff66FF66ON|r" or "|cffFF6666OFF|r"
        print("|cff4FC3F7Laksefisk|r auto-open containers: " .. state)

    elseif cmd == "resetbar" then
        local startX = (GetScreenWidth() - NUM_PIXELS * PIXEL_STEP) / 2
        barFrame:ClearAllPoints()
        barFrame:SetPoint("BOTTOMLEFT", UIParent, "BOTTOMLEFT", startX, BAR_Y_OFFSET)
        LaksefiskDB.barPos = nil
        print("|cff4FC3F7Laksefisk|r pixel bar reset to default position")

    elseif cmd == "status" then
        showStatusBar = not showStatusBar
        LaksefiskDB.showStatusBar = showStatusBar
        if showStatusBar then
            if statusFrame then statusFrame:Show() end
        else
            if statusFrame then statusFrame:Hide() end
        end

    elseif cmd == "settings" then
        showSettingsPanel = not showSettingsPanel
        if showSettingsPanel then
            if settingsFrame then settingsFrame:Show() end
        else
            if settingsFrame then settingsFrame:Hide() end
        end

    else
        print("|cff4FC3F7Laksefisk|r commands:")
        print("  /lf show | hide | debug")
        print("  /lf status  (toggle status bar)")
        print("  /lf settings  (toggle settings panel)")
        print("  /lf test | test2 | test3  (fake loot)")
        print("  /lf whisper | say | yell  (fake chat)")
        print("  /lf nearby  (toggle nearby player chat alerts)")
        print("  /lf nameplates  (toggle auto-enable friendly nameplates)")

        print("  /lf dead  (toggle dead)")
        print("  /lf open  (open all containers in bags)")
        print("  /lf containers  (toggle auto-open containers)")
        print("  /lf move  (unlock/lock pixel bar for dragging)")
        print("  /lf resetbar  (reset pixel bar to default position)")
        print("  /lf delete add <name>  (auto-delete fish)")
        print("  /lf delete remove <name>")
        print("  /lf delete list | clear | debug")
        print("  /lf whitelist add <name>  (ignore player)")
        print("  /lf whitelist remove <name>")
        print("  /lf whitelist list | clear")
        print("  /lf skip party | guild | friends  (toggle auto-skip)")
    end
end
