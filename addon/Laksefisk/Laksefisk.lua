-- Laksefisk Pixel Bridge v8
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
--
-- The pixel bar is placed at the bottom-centre of the screen.

local PIXEL_SIZE = 5
local PIXEL_GAP = 0
local PIXEL_STEP = PIXEL_SIZE + PIXEL_GAP
local NUM_PIXELS = 20       -- 0-7 control + 8-13 item ID + 14-16 bait + 17-19 hp
local BAR_Y_OFFSET = 120
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
local mouseoverBobber = false  -- true when GameTooltip shows "Fishing Bobber"
local junkOnCursor = false
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
local printNearby = true
local scanNameplates = true
local enforceNameplates = true

-- Pixel textures
local pixels = {}
local barFrame

---------------------------------------------------------------------------
-- Helpers
---------------------------------------------------------------------------

local function SetPixelRaw(index, r, g, b)
    if pixels[index] then
        pixels[index]:SetColorTexture(r / 255, g / 255, b / 255, 1)
    end
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

local function ScanNearbyPlayers()
    if not scanNameplates then
        playerNearby = false
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
        if unit and UnitIsPlayer(unit) and not UnitIsUnit(unit, "player") then
            local name = UnitName(unit)
            if name and not nearbyPlayers[name] and printNearby then
                print("|cff4FC3F7Laksefisk|r |cffFF6666player nearby:|r " .. name)
            end
            if name then
                nearbyPlayers[name] = now + NEARBY_TIMEOUT
            end
        end
    end

    -- Expire old entries
    local anyNearby = false
    for name, expiry in pairs(nearbyPlayers) do
        if now > expiry then
            nearbyPlayers[name] = nil
        else
            anyNearby = true
        end
    end

    playerNearby = anyNearby
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
-- Create the pixel bar
---------------------------------------------------------------------------

local barMovable = false

local function CreatePixelBar()
    local totalW = NUM_PIXELS * PIXEL_STEP
    local startX = (GetScreenWidth() - totalW) / 2

    barFrame = CreateFrame("Frame", "LaksefiskBar", UIParent)
    barFrame:SetSize(totalW, PIXEL_SIZE)

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
        px:SetPoint("LEFT", barFrame, "LEFT", i * PIXEL_STEP, 0)
        px:SetColorTexture(0, 0, 0, 1)
        pixels[i] = px
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

eventFrame:SetScript("OnEvent", function(self, event, ...)
    if event == "PLAYER_LOGIN" then
        LaksefiskDB = LaksefiskDB or {}
        LaksefiskDB.deleteList = LaksefiskDB.deleteList or {}
        LaksefiskDB.debugDelete = LaksefiskDB.debugDelete or false
        if LaksefiskDB.autoOpenContainers == nil then LaksefiskDB.autoOpenContainers = true end
        CreatePixelBar()
        local nDel = #LaksefiskDB.deleteList
        local cStr = LaksefiskDB.autoOpenContainers and "ON" or "OFF"
        print("|cff4FC3F7Laksefisk|r pixel bridge v8 loaded (" .. NUM_PIXELS .. " pixels, " .. nDel .. " auto-delete, containers " .. cStr .. ")")

    elseif event == "PLAYER_DEAD" then
        isDead = true

    elseif event == "PLAYER_ALIVE" or event == "PLAYER_UNGHOST" then
        isDead = false

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
            end
        end

    elseif event == "UNIT_SPELLCAST_CHANNEL_STOP" then
        local unit = ...
        if unit == "player" then
            isFishing = false
        end

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
            print("    - " .. name)
            nCount = nCount + 1
        end
        if nCount == 0 then print("    (none)") end
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

    elseif cmd == "move" then
        barMovable = not barMovable
        barFrame:EnableMouse(barMovable)
        if barMovable then
            -- Make bar bigger and visible while moving
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, 20)
            print("|cff4FC3F7Laksefisk|r pixel bar |cff66FF66UNLOCKED|r — drag to move, then /lf move to lock")
        else
            barFrame:SetSize(NUM_PIXELS * PIXEL_STEP, PIXEL_SIZE)
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

    else
        print("|cff4FC3F7Laksefisk|r commands:")
        print("  /lf show | hide | debug")
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
    end
end
