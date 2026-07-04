"""Expedition leg registry for `.expedition`: the only way to earn
Population. Same shape as econ/data/ventures.py's VENTURE_PATHS (pick
one of a few risk tiers, each a real success/loss gamble) except the
payout is Population, not gold, and each of an expedition's 5 legs is
resolved on its own, 15 minutes apart -- see econ/formulas.py's
".expedition" section for the pacing/reward math, cogs/town.py for the
UI.

success = win chance (0-1)
reward  = (min, max) Population gained on success, before Fame scales it
loss    = (min, max) Population lost on failure (0, 0) for a safe miss
"""

from .. import formulas

EXPEDITION_CHOICES = {
    "steady_path": {
        "name": "Keep to the Steady Path", "emoji": "🥾", "risk": "Low risk",
        "success": 0.90, "reward": (10, 18), "loss": (0, 0),
        "success_flavour": [
            "A quiet stretch of road brings a few willing families along with you.",
            "Word of your town spreads well at a wayside inn.",
            "A small band of travellers decides your town sounds worth the walk.",
        ],
        "fail_flavour": [
            "Nothing comes of it -- an uneventful, empty-handed day.",
            "The road's quiet, and so is everyone you meet on it.",
        ],
    },
    "unmarked_trail": {
        "name": "Strike Out on an Unmarked Trail", "emoji": "🧭", "risk": "Medium risk",
        "success": 0.65, "reward": (24, 42), "loss": (0, 12),
        "success_flavour": [
            "You lead a whole hamlet, spooked off their own land, back to your gates.",
            "A trapper's family, tired of the wilds, asks to settle with you.",
            "You broker peace with a wary camp, and they choose to stay.",
        ],
        "fail_flavour": [
            "You lose the trail entirely, and some who came with you turn back for good.",
            "A bad river crossing costs you supplies -- and a few settlers' nerve.",
        ],
    },
    "wild_frontier": {
        "name": "Push Into the Wild Frontier", "emoji": "🏔️", "risk": "High risk",
        "success": 0.42, "reward": (60, 110), "loss": (10, 25),
        "success_flavour": [
            "You talk down a whole frontier outpost, and they march back with you in force.",
            "An entire lost caravan of settlers, given up for gone, follows you home.",
            "You strike a bold bargain with a frontier lord for a full village's worth of people.",
        ],
        "fail_flavour": [
            "The frontier turns on you -- some who'd already pledged to come turn back scattered and afraid.",
            "A rough encounter sends everyone fleeing, including a few of your own townsfolk.",
        ],
    },
}

EXPEDITION_CHOICE_ORDER = ["steady_path", "unmarked_trail", "wild_frontier"]

assert len(EXPEDITION_CHOICES) == len(EXPEDITION_CHOICE_ORDER) == 3


# Permanent expedition upgrades (see formulas.py's "expedition upgrades"
# section for cost/effect math): 4 perks, one claimed per purchase, each
# struck off the list for good once picked.
EXPEDITION_UPGRADE_PERKS = {
    "population": {
        "name": "Well-Stocked Wagons", "emoji": "🎒",
        "effect": f"+{round(formulas.EXPEDITION_UPGRADE_POPULATION_BONUS * 100)}% "
                  "Population earned per successful leg",
    },
    "legs": {
        "name": "Hardier Settlers", "emoji": "🥾",
        "effect": f"+{formulas.EXPEDITION_UPGRADE_EXTRA_LEGS} leg per trip "
                  f"({formulas.EXPEDITION_LEGS} -> {formulas.EXPEDITION_LEGS + formulas.EXPEDITION_UPGRADE_EXTRA_LEGS})",
    },
    "cooldown": {
        "name": "Seasoned Guides", "emoji": "⏱️",
        "effect": f"-{round(formulas.EXPEDITION_UPGRADE_COOLDOWN_CUT * 100)}% wait between legs",
    },
    "success": {
        "name": "Sharper Scouts", "emoji": "🔭",
        "effect": f"+{round(formulas.EXPEDITION_UPGRADE_SUCCESS_BONUS * 100)}pp success chance, every choice",
    },
}

EXPEDITION_UPGRADE_PERK_ORDER = ["population", "legs", "cooldown", "success"]

assert len(EXPEDITION_UPGRADE_PERKS) == len(EXPEDITION_UPGRADE_PERK_ORDER) == formulas.EXPEDITION_UPGRADE_MAX_LEVEL
