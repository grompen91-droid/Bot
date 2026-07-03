"""Job registry. Add a trade here (plus its items in items.py and tools in
tools.py) and every command, job board, work, market, shop, picks it up.

cooldown           = base seconds between works (skill reduces it, see formulas)
tip                = (min, max) bonus coins per work before scaling
unlock_total_level = sum of all skill levels required to take the trade
yields             = (item_key, min_qty, max_qty, weight), one is rolled
                     per work, weighted; rare+ items get luckier with level
category           = "guild" (the 8 honest trades) or "criminal" (the one
                     dishonest one); the job board lists them separately
max_infamy         = None (no reputation check) or the infamy above which
                     that guild refuses to take you on, different per
                     trade -- the more respectable the trade, the less
                     they'll tolerate a notorious criminal. Only "guild"
                     trades use this.
"""

from .items import ITEMS

JOBS = {
    "farmer": {
        "name": "Farmer", "emoji": "🌾", "cooldown": 60, "tip": (2, 6),
        "unlock_total_level": 0, "category": "guild", "max_infamy": None,
        "description": "Till the fields and bring in the harvest.",
        "yields": [
            ("wheat", 3, 7, 42), ("carrot", 2, 5, 30), ("apple", 2, 4, 18),
            ("pumpkin", 1, 2, 9), ("golden_apple", 1, 1, 1),
        ],
        "flavour": [
            "You toil in the sun-baked fields from dawn till dusk.",
            "You swing your sickle through golden rows of grain.",
            "You dig through rich soil in the lord's back acres.",
            "A scarecrow watches over you as you gather the harvest.",
        ],
    },
    "miner": {
        "name": "Miner", "emoji": "⛏️", "cooldown": 60, "tip": (2, 6),
        "unlock_total_level": 0, "category": "guild", "max_infamy": None,
        "description": "Delve into the mountain for ore and gems.",
        "yields": [
            ("stone", 3, 8, 38), ("coal", 2, 6, 30), ("iron_ore", 2, 4, 20),
            ("gold_ore", 1, 2, 8), ("ruby", 1, 1, 3), ("dragon_gem", 1, 1, 1),
        ],
        "flavour": [
            "You descend into the torch-lit depths of the mountain.",
            "Your pick rings out against the cold stone.",
            "Dust fills the tunnel as you chip away at a rich vein.",
            "You follow an old dwarven seam deeper underground.",
        ],
    },
    "fisherman": {
        "name": "Fisherman", "emoji": "🎣", "cooldown": 60, "tip": (2, 6),
        "unlock_total_level": 0, "category": "guild", "max_infamy": None,
        "description": "Cast your line into river and sea.",
        "yields": [
            ("herring", 2, 6, 38), ("trout", 2, 4, 30), ("salmon", 1, 3, 20),
            ("pike", 1, 2, 8), ("royal_sturgeon", 1, 1, 3), ("kraken_scale", 1, 1, 1),
        ],
        "flavour": [
            "You cast your line off the old stone bridge.",
            "Mist rolls over the water as you haul in your net.",
            "You row out past the reeds at first light.",
            "The river runs high and the fish are biting.",
        ],
    },
    "lumberjack": {
        "name": "Lumberjack", "emoji": "🪓", "cooldown": 60, "tip": (2, 6),
        "unlock_total_level": 5, "category": "guild", "max_infamy": 250,
        "description": "Fell the great trees of the king's forest.",
        "yields": [
            ("birch_log", 3, 7, 42), ("oak_log", 2, 5, 32), ("maple_log", 1, 3, 18),
            ("heartwood", 1, 1, 6), ("elderbark", 1, 1, 2),
        ],
        "flavour": [
            "Your axe bites deep and the tree groans overhead.",
            "You work the edge of the king's forest, chips flying.",
            "Timber! A mighty oak crashes to the forest floor.",
            "You haul split logs back along the muddy cart track.",
        ],
    },
    "hunter": {
        "name": "Hunter", "emoji": "🏹", "cooldown": 70, "tip": (3, 7),
        "unlock_total_level": 12, "category": "guild", "max_infamy": 180,
        "description": "Stalk game through wood and moor.",
        "yields": [
            ("rabbit", 1, 3, 36), ("pelt", 1, 3, 30), ("venison", 1, 2, 22),
            ("boar", 1, 1, 10), ("white_stag", 1, 1, 2),
        ],
        "flavour": [
            "You track fresh prints through the morning frost.",
            "An arrow flies true from your longbow.",
            "You wait downwind, still as stone, until the moment strikes.",
            "The hounds flush your quarry from the thicket.",
        ],
    },
    "baker": {
        "name": "Baker", "emoji": "🍞", "cooldown": 75, "tip": (3, 8),
        "unlock_total_level": 22, "category": "guild", "max_infamy": 100,
        "description": "Fill the town square with the smell of fresh bread.",
        "yields": [
            ("bread", 2, 4, 48), ("meat_pie", 1, 3, 34),
            ("honey_cake", 1, 2, 16), ("kings_feast", 1, 1, 2),
        ],
        "flavour": [
            "The ovens roar as you knead dough before sunrise.",
            "Flour hangs in the air of your little bakery.",
            "Townsfolk queue at your window for the morning batch.",
            "You pull a tray of golden loaves from the brick oven.",
        ],
    },
    "brewer": {
        "name": "Brewer", "emoji": "🍺", "cooldown": 80, "tip": (3, 9),
        "unlock_total_level": 35, "category": "guild", "max_infamy": 70,
        "description": "Brew ale and mead for thirsty townsfolk.",
        "yields": [
            ("ale", 2, 4, 50), ("mead", 1, 3, 36),
            ("royal_wine", 1, 1, 12), ("dwarven_stout", 1, 1, 2),
        ],
        "flavour": [
            "The tavern cellar bubbles with fresh barrels.",
            "You stir the mash and breathe in the sweet steam.",
            "A new batch of mead is ready for the tapping.",
            "The innkeeper pays well for your finest barrel.",
        ],
    },
    "tanner": {
        "name": "Tanner", "emoji": "🥾", "cooldown": 83, "tip": (3, 9),
        "unlock_total_level": 40, "category": "guild", "max_infamy": 55,
        "description": "Cure hides into supple leather for saddle and boot.",
        "yields": [
            ("hide", 3, 7, 48), ("cured_leather", 2, 4, 34),
            ("supple_hide", 1, 1, 15), ("direwolf_pelt", 1, 1, 3),
        ],
        "flavour": [
            "You scrape the hide clean under the tannery's low rafters.",
            "The curing pit reeks, but the leather beneath is flawless.",
            "You work oil deep into the grain until it gleams.",
            "A trapper sells you a fresh hide still warm from the hunt.",
        ],
    },
    "jeweler": {
        "name": "Jeweler", "emoji": "🔍", "cooldown": 87, "tip": (4, 10),
        "unlock_total_level": 45, "category": "guild", "max_infamy": 48,
        "description": "Cut and polish gemstones fit for a crown.",
        "yields": [
            ("rough_gem", 2, 4, 48), ("cut_gem", 1, 3, 34),
            ("brilliant_gem", 1, 1, 15), ("starlight_gem", 1, 1, 3),
        ],
        "flavour": [
            "You turn a rough stone slowly against the wheel, chasing the light.",
            "A single perfect facet catches the candlelight just right.",
            "You polish away the dust to find fire trapped inside the stone.",
            "A noble's steward pays handsomely for a matched pair of cuts.",
        ],
    },
    "alchemist": {
        "name": "Alchemist", "emoji": "🧪", "cooldown": 90, "tip": (4, 10),
        "unlock_total_level": 50, "category": "guild", "max_infamy": 40,
        "description": "Brew potions and strange tinctures in your tower.",
        "yields": [
            ("herbs", 2, 5, 48), ("minor_potion", 1, 2, 36),
            ("elixir", 1, 1, 13), ("philosophers_dust", 1, 1, 3),
        ],
        "flavour": [
            "Strange vapours curl from your bubbling cauldron.",
            "You grind rare herbs by candlelight in the tower.",
            "The mixture flashes green, a successful brew!",
            "You barter with a travelling herbalist for reagents.",
        ],
    },
    "criminal": {
        "name": "Criminal", "emoji": "🗡️", "cooldown": 55, "tip": (0, 0),
        "unlock_total_level": 0, "category": "criminal", "max_infamy": None,
        "description": "Live outside the law. No goods, no guild, no honest coin.",
        "yields": [],
        "flavour": [],
    },
}

# Registry sanity: every yield must reference a real item.
for _job_key, _info in JOBS.items():
    for _item, _lo, _hi, _w in _info["yields"]:
        if _item not in ITEMS:
            raise RuntimeError(f"Job {_job_key!r} yields unknown item {_item!r}")

# The hardest trade to unlock, used to anchor the per-job minigame
# reward/cooldown curves (see formulas.py's minigame_round_base et al).
MAX_JOB_UNLOCK_LEVEL = max(info["unlock_total_level"] for info in JOBS.values())


def resolve_job(query: str) -> str | None:
    """Fuzzy-match a user-typed trade name ('farmer', 'Fisher', '🌾')."""
    q = query.strip().lower()
    if q in JOBS:
        return q
    for key, info in JOBS.items():
        if q in (info["name"].lower(), info["emoji"]):
            return key
    for key, info in JOBS.items():
        if info["name"].lower().startswith(q) or key.startswith(q):
            return key
    return None
