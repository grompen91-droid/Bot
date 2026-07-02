"""Consumable registry: which items grant a temporary buff when used
with .use, and what that buff does. Not every item is consumable --
only the ones listed here (a mix of small drops from ordinary .work,
Alchemist potions from .brew, and a few of the "food and drink"
recipes from .craft; gear-like crafted goods like the Reinforced
Toolkit or Dragonforged Blade stay sell-only).

effect    = "cooldown" (multiplicative reduction, e.g. 0.20 = -20%
            shorter), "xp" (multiplicative boost, e.g. 0.50 = +50%),
            or "gold" (multiplicative boost, e.g. 0.15 = +15%)
magnitude = the fraction above, always positive
duration  = how long the buff lasts once used, in seconds
source    = where it can come from, for flavour only

Using an item whose buff is already active EXTENDS the remaining
duration by another full copy rather than resetting it (see
econ/buffs.py's extend_expiry), capped at MAX_STACK_MULTIPLIER x the
item's own duration so chaining the same cheap item forever can't buy
a permanent buff. Only one timer per item ever exists (the DB row is
keyed by item, not a generated buff id), so you can't hold two
separate copies of the exact same buff. Two DIFFERENT items with the
same effect (e.g. two different gold buffs) DO stack additively while
both are active, up to the MAX_GOLD_BONUS/MAX_XP_BONUS/
MAX_COOLDOWN_REDUCTION caps in econ/buffs.py.
"""

CONSUMABLES = {
    # ── small, short drops from ordinary .work (any trade) ────────────────
    "travelers_snack": {
        "effect": "cooldown", "magnitude": 0.10, "duration": 30 * 60,
        "description": "-10% cooldown for 30 minutes", "source": "a rare find while working",
    },
    "lucky_coin": {
        "effect": "gold", "magnitude": 0.10, "duration": 30 * 60,
        "description": "+10% gold for 30 minutes", "source": "a rare find while working",
    },
    "focus_draught": {
        "effect": "xp", "magnitude": 0.20, "duration": 30 * 60,
        "description": "+20% XP for 30 minutes", "source": "a rare find while working",
    },
    # ── Alchemist potions, from .brew ──────────────────────────────────────
    "potion_of_haste": {
        "effect": "cooldown", "magnitude": 0.20, "duration": 2 * 60 * 60,
        "description": "-20% cooldown for 2 hours", "source": "brewing",
    },
    "potion_of_insight": {
        "effect": "xp", "magnitude": 0.50, "duration": 2 * 60 * 60,
        "description": "+50% XP for 2 hours", "source": "brewing",
    },
    "potion_of_fortune": {
        "effect": "gold", "magnitude": 0.15, "duration": 2 * 60 * 60,
        "description": "+15% gold for 2 hours", "source": "brewing",
    },
    # ── crafted food & drink (see econ/data/recipes.py) ────────────────────
    "hearty_stew": {
        "effect": "cooldown", "magnitude": 0.15, "duration": 60 * 60,
        "description": "-15% cooldown for 1 hour", "source": "crafting",
    },
    "fishermans_basket": {
        "effect": "xp", "magnitude": 0.30, "duration": 60 * 60,
        "description": "+30% XP for 1 hour", "source": "crafting",
    },
    "spiced_mead_cask": {
        "effect": "gold", "magnitude": 0.20, "duration": 90 * 60,
        "description": "+20% gold for 1.5 hours", "source": "crafting",
    },
    "alchemical_tonic": {
        "effect": "xp", "magnitude": 0.60, "duration": 2 * 60 * 60,
        "description": "+60% XP for 2 hours", "source": "crafting",
    },
    "feast_of_kings": {
        "effect": "gold", "magnitude": 0.35, "duration": 3 * 60 * 60,
        "description": "+35% gold for 3 hours", "source": "crafting",
    },
    "philosophers_masterwork": {
        "effect": "gold", "magnitude": 0.50, "duration": 4 * 60 * 60,
        "description": "+50% gold for 4 hours", "source": "crafting",
    },
}

# Random work-drop pool: a low chance on any .work to also find one of
# these, regardless of trade.
WORK_DROP_CONSUMABLES = ["travelers_snack", "lucky_coin", "focus_draught"]
WORK_DROP_CHANCE = 0.04

# Brew potion pool: a chance on a successful .brew to also receive one
# of these, on top of the usual gold. Perfect brews always get one.
BREW_POTIONS = ["potion_of_haste", "potion_of_insight", "potion_of_fortune"]
BREW_POTION_CHANCE = 0.35
