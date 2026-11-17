-- FishingInteract: lets the Interact key (or controller button) reel in your bobber,
-- and gives you a Fish key that puts your best lure on the pole when it has none.
--
-- Soft interact: only while Fishing is being cast, your values are noted and the
-- fishing values set. When the cast ends (catch, timeout, interrupt) or you log
-- out, your values go back. If WoW closed mid-cast, they go back at the next login.
--
-- Fish key (Key Bindings > FishingInteract): if a fishing pole is in your hands with
-- no lure on it and you have a lure in your bags, it puts the best one on.
-- Otherwise it casts Fishing. WoW only lets items be used from a key press, so the
-- lure goes on when you press the key, and the next press fishes.
--
-- At login it binds the keys FishingTrainer presses (Keys.lua, which FishingTrainer's
-- window rewrites): Fish (] unless you pick another) and Interact with Target ([).
-- A key that already does something else is left alone, and chat says so.
--
-- /fishinteract           shows the settings and your lures
-- /fishinteract defaults  resets the soft-interact settings to WoW's defaults

local ADDON = ...

---------------------------------------------------------------------------
-- Soft interact while fishing
---------------------------------------------------------------------------

-- What the Interact key needs to reach the bobber
local FISHING = {
    SoftTargetInteract = "3",          -- soft interact on, for keyboard and controller
    SoftTargetInteractRange = "30",    -- far enough to reach the bobber
    SoftTargetIconGameObject = "0",    -- no gear icon over the bobber: FishingTrainer watches the bobber
                                       -- itself on screen, and took the icon for it
}
-- Settings whose fishing value can't be a leftover from an older version of this addon
local OWN_VALUE_OK = { SoftTargetIconGameObject = true }
-- Everything "/fishinteract defaults" resets
local SOFT_INTERACT = { "SoftTargetInteract", "SoftTargetInteractRange",
                        "SoftTargetIconGameObject", "SoftTargetInteractArc" }

local C = C_CVar or {}
local GetCVar = C.GetCVar or _G.GetCVar
local SetCVar = C.SetCVar or _G.SetCVar
local GetCVarDefault = C.GetCVarDefault or _G.GetCVarDefault

local FISHING_SPELL = 7620   -- Fishing. Its name is compared, so every rank and language matches.

local db        -- FishingInteractDB; db.saved holds your values while the fishing values are on
local pending   -- a settings change waiting for combat to end
local frame = CreateFrame("Frame")

local function say(msg)
    print("|cff33ccffFishingInteract|r: " .. msg)
end

local function spellName(id)
    if C_Spell and C_Spell.GetSpellName then return C_Spell.GetSpellName(id) end
    if GetSpellInfo then return (GetSpellInfo(id)) end
end

local function isFishing(spellID)
    local name = UnitChannelInfo("player") or (spellID and spellName(spellID))
    return name ~= nil and (name == spellName(FISHING_SPELL) or name == "Fishing")
end

local function switchOn()
    if not db.saved then
        local saved = {}
        for name, value in pairs(FISHING) do
            local current = GetCVar(name)
            -- Already at the fishing value: left over from before, so WoW's default is yours
            if current == nil or (not OWN_VALUE_OK[name] and tonumber(current) == tonumber(value)) then
                current = GetCVarDefault(name)
            end
            saved[name] = current
        end
        db.saved = saved
    end
    for name, value in pairs(FISHING) do SetCVar(name, value) end
end

local function putBack()
    if not db.saved then return end
    for name, value in pairs(db.saved) do SetCVar(name, value) end
    db.saved = nil
end

local function apply(on)
    if InCombatLockdown() then          -- some settings can't change in combat
        pending = true
        frame:RegisterEvent("PLAYER_REGEN_ENABLED")
        return
    end
    pending = nil
    if on then switchOn() else putBack() end
end

---------------------------------------------------------------------------
-- Lures
---------------------------------------------------------------------------

-- Fishing lures and how much Fishing they add. Lures not listed here are found by
-- their description: "When applied to your fishing pole, increases Fishing by N".
local LURES = {
    [6529] = 25,    -- Shiny Bauble
    [6530] = 50,    -- Nightcrawlers
    [6811] = 50,    -- Aquadynamic Fish Lens
    [6532] = 75,    -- Bright Baubles
    [7307] = 75,    -- Flesh Eating Worm
    [6533] = 100,   -- Aquadynamic Fish Attractor
}
local MAIN_HAND = 16
local WEAPON, FISHING_POLE, CONSUMABLE = 2, 20, 0   -- item classes and the fishing pole subclass

local Container = C_Container or {}
local GetContainerNumSlots = Container.GetContainerNumSlots or _G.GetContainerNumSlots
local GetContainerItemID = Container.GetContainerItemID or _G.GetContainerItemID
local GetItemInfoInstant = (C_Item and C_Item.GetItemInfoInstant) or _G.GetItemInfoInstant

local described = {}   -- itemID -> Fishing bonus or false, read from item descriptions

local scanTip
local function descriptionLines(bag, slot)
    local lines = {}
    if C_TooltipInfo and C_TooltipInfo.GetBagItem then
        local data = C_TooltipInfo.GetBagItem(bag, slot)
        if data and TooltipUtil and TooltipUtil.SurfaceArgs then TooltipUtil.SurfaceArgs(data) end
        for _, line in ipairs(data and data.lines or {}) do
            if TooltipUtil and TooltipUtil.SurfaceArgs then TooltipUtil.SurfaceArgs(line) end
            lines[#lines + 1] = line.leftText
        end
        return lines
    end
    if not scanTip then   -- older clients: read a hidden tooltip
        scanTip = CreateFrame("GameTooltip", "FishingInteractScanTip", nil, "GameTooltipTemplate")
        scanTip:SetOwner(WorldFrame, "ANCHOR_NONE")
    end
    scanTip:ClearLines()
    scanTip:SetBagItem(bag, slot)
    for i = 1, scanTip:NumLines() do
        local text = _G["FishingInteractScanTipTextLeft" .. i]
        lines[#lines + 1] = text and text:GetText()
    end
    return lines
end

local function lureBonus(itemID, bag, slot)
    if LURES[itemID] then return LURES[itemID] end
    if described[itemID] == nil then
        local classID = select(6, GetItemInfoInstant(itemID))
        if classID ~= CONSUMABLE then
            described[itemID] = false
        else
            local lines = descriptionLines(bag, slot)
            if #lines > 0 then         -- only remember once the description has loaded
                described[itemID] = false
                for _, text in ipairs(lines) do
                    local bonus = text and text:match("[Ff]ishing [Pp]ole.-[Ff]ishing by (%d+)")
                    if bonus then described[itemID] = tonumber(bonus) break end
                end
            end
        end
    end
    return described[itemID] or nil
end

-- The lure in your bags that adds the most Fishing
local function bestLure()
    local bestID, bestBonus
    for bag = 0, NUM_BAG_SLOTS or 4 do
        for slot = 1, GetContainerNumSlots(bag) or 0 do
            local id = GetContainerItemID(bag, slot)
            local bonus = id and lureBonus(id, bag, slot)
            if bonus and (not bestBonus or bonus > bestBonus) then
                bestID, bestBonus = id, bonus
            end
        end
    end
    return bestID, bestBonus
end

local function holdingPole()
    local id = GetInventoryItemID("player", MAIN_HAND)
    if not id then return false end
    local _, _, _, _, _, classID, subclassID = GetItemInfoInstant(id)
    return classID == WEAPON and subclassID == FISHING_POLE
end

local function poleHasLure()
    return (GetWeaponEnchantInfo()) and true or false   -- first value: the main hand has one
end

local function itemName(id)
    local name = (C_Item and C_Item.GetItemNameByID and C_Item.GetItemNameByID(id))
                 or (GetItemInfo and GetItemInfo(id))
    return name or ("item " .. id)
end

-- What the Fish key does right now
local function fishMacro()
    if holdingPole() and not poleHasLure() then
        local lure, bonus = bestLure()
        if lure then
            return "/use item:" .. lure .. "\n/use " .. MAIN_HAND, lure, bonus
        end
    end
    return "/cast " .. (spellName(FISHING_SPELL) or "Fishing")
end

---------------------------------------------------------------------------
-- The Fish key
---------------------------------------------------------------------------

BINDING_HEADER_FISHINGINTERACT = "FishingInteract"
_G["BINDING_NAME_CLICK FishingInteractButton:LeftButton"] = "Fish (puts your best lure on first if the pole has none)"

local FISH_ACTION = "CLICK FishingInteractButton:LeftButton"
local INTERACT_ACTION = "INTERACTTARGET"
-- The keys FishingTrainer presses: Keys.lua, which its window rewrites when you change them
local KEYS = type(FishingInteract_Keys) == "table" and FishingInteract_Keys or {}
local FISH_KEY = strupper(KEYS.fish or "]")
local INTERACT_KEY = strupper(KEYS.interact or "[")

---Put action on key, unless that key already does something else: then say so instead of
---taking it from you. A key holding the other FishingTrainer action is fair game (the two
---keys were swapped). Returns true when it changed a binding.
local function bindKey(key, action, label, where, other)
    local current = GetBindingAction(key)
    if current == action then return false end
    if current and current ~= "" and current ~= other then
        say(key .. " already does " .. current .. ", so FishingTrainer can't use it for " .. label .. "."
            .. " Key Bindings > " .. where .. ": put " .. label .. " on " .. key
            .. ", or pick another key in FishingTrainer's window.")
        return false
    end
    if SetBinding(key, action) then
        say(label .. " is now on " .. key .. ", the key FishingTrainer presses.")
        return true
    end
    return false
end

---Bind FishingTrainer's two keys. Fish is only ever FishingTrainer's, so its old keys are
---cleared; your own Interact keys are left alone.
local function bindTrainerKeys()
    if InCombatLockdown() or not (GetBindingAction and SetBinding) then return end
    if FISH_KEY == INTERACT_KEY then
        say("the Fish and Interact keys are both " .. FISH_KEY .. ": pick two keys in FishingTrainer's window.")
        return
    end
    local changed = false
    if GetBindingKey then
        for _, old in ipairs({ GetBindingKey(FISH_ACTION) }) do
            if old ~= FISH_KEY and old ~= INTERACT_KEY then
                SetBinding(old)
                changed = true
            end
        end
    end
    changed = bindKey(FISH_KEY, FISH_ACTION, "Fish", "FishingInteract", INTERACT_ACTION) or changed
    changed = bindKey(INTERACT_KEY, INTERACT_ACTION, "Interact with Target", "Targeting", FISH_ACTION) or changed
    if changed and SaveBindings and GetCurrentBindingsSet then SaveBindings(GetCurrentBindingsSet()) end
end

local fishButton = CreateFrame("Button", "FishingInteractButton", UIParent, "SecureActionButtonTemplate")
-- WoW's own button code fires once, on key down or key up as your settings say
fishButton:RegisterForClicks("AnyDown", "AnyUp")
local buttonReady = false

local function setUpButton()
    if buttonReady or InCombatLockdown() then return end
    fishButton:SetAttribute("type", "macro")
    fishButton:SetAttribute("macrotext", (fishMacro()))
    buttonReady = true
end

-- Decide just before each press; items can't be switched in combat, so the last choice stays
fishButton:SetScript("PreClick", function(self, _, down)
    if InCombatLockdown() then return end
    local macro, lure, bonus = fishMacro()
    if macro ~= self:GetAttribute("macrotext") then
        self:SetAttribute("macrotext", macro)
    end
    if lure and down ~= false then
        say("putting " .. itemName(lure) .. " (+" .. bonus .. " Fishing) on your pole. Press again to fish.")
    end
end)

setUpButton()

---------------------------------------------------------------------------
-- Events and the chat command
---------------------------------------------------------------------------

frame:SetScript("OnEvent", function(self, event, arg1, _, arg3)
    if event == "ADDON_LOADED" then
        if arg1 == ADDON then
            FishingInteractDB = FishingInteractDB or {}
            db = FishingInteractDB
        end
        return
    end
    if not db then return end

    if event == "PLAYER_LOGIN" then
        setUpButton()
        bindTrainerKeys()
        if db.saved and not isFishing() then   -- WoW closed mid-cast last time
            apply(false)
            say("your soft-interact settings were still set for fishing from last time; they're back now.")
        end
    elseif event == "UNIT_SPELLCAST_CHANNEL_START" then
        if arg1 == "player" and isFishing(arg3) then apply(true) end
    elseif event == "UNIT_SPELLCAST_CHANNEL_STOP" then
        if arg1 == "player" and (db.saved or pending) then apply(false) end
    elseif event == "PLAYER_REGEN_ENABLED" then
        setUpButton()
        if pending then apply(isFishing()) end
        if not pending then self:UnregisterEvent("PLAYER_REGEN_ENABLED") end
    elseif event == "PLAYER_LOGOUT" then
        putBack()                               -- so WoW saves your own values
    end
end)

frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:RegisterEvent("UNIT_SPELLCAST_CHANNEL_START")
frame:RegisterEvent("UNIT_SPELLCAST_CHANNEL_STOP")
if not buttonReady then frame:RegisterEvent("PLAYER_REGEN_ENABLED") end

SLASH_FISHINGINTERACT1 = "/fishinteract"
SlashCmdList.FISHINGINTERACT = function(msg)
    msg = strlower(strtrim(msg or ""))
    if msg == "defaults" then
        if InCombatLockdown() then
            say("can't change settings in combat.")
            return
        end
        db.saved = nil
        for _, name in ipairs(SOFT_INTERACT) do SetCVar(name, GetCVarDefault(name)) end
        say("soft-interact settings reset to WoW's defaults.")
    end
    for _, name in ipairs(SOFT_INTERACT) do
        say(name .. " = " .. tostring(GetCVar(name)) .. "  (default " .. tostring(GetCVarDefault(name)) .. ")")
    end
    say(db.saved and "fishing values on: you're fishing." or "your own values are on.")

    local lure, bonus = bestLure()
    say("Pole: " .. (not holdingPole() and "not in your hands"
                     or poleHasLure() and "has a lure on" or "no lure on")
        .. ". Best lure in bags: " .. (lure and (itemName(lure) .. " (+" .. bonus .. ")") or "none") .. ".")
    if not GetBindingKey("CLICK FishingInteractButton:LeftButton") then
        say("The Fish key isn't bound yet: Key Bindings > FishingInteract.")
    end
end
