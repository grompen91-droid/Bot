"""Job, item, and tool definitions for the medieval economy."""

# Every item that can appear in an inventory.
# value = base sell price in gold (fluctuates daily at the market).
ITEMS = {
    # Farmer
    "wheat":           {"name": "Wheat",            "emoji": "🌾", "value": 3},
    "carrot":          {"name": "Carrot",           "emoji": "🥕", "value": 4},
    "apple":           {"name": "Apple",            "emoji": "🍎", "value": 6},
    "pumpkin":         {"name": "Pumpkin",          "emoji": "🎃", "value": 14},
    # Miner
    "stone":           {"name": "Stone",            "emoji": "🪨", "value": 2},
    "coal":            {"name": "Coal",             "emoji": "⚫", "value": 4},
    "iron_ore":        {"name": "Iron Ore",         "emoji": "⛓️", "value": 7},
    "gold_ore":        {"name": "Gold Ore",         "emoji": "🟡", "value": 18},
    "ruby":            {"name": "Ruby",             "emoji": "💎", "value": 45},
    # Fisherman
    "herring":         {"name": "Herring",          "emoji": "🐟", "value": 3},
    "trout":           {"name": "Trout",            "emoji": "🐠", "value": 6},
    "salmon":          {"name": "Salmon",           "emoji": "🍣", "value": 9},
    "pike":            {"name": "Pike",             "emoji": "🦈", "value": 15},
    "royal_sturgeon":  {"name": "Royal Sturgeon",   "emoji": "👑", "value": 50},
    # Lumberjack
    "birch_log":       {"name": "Birch Log",        "emoji": "🪵", "value": 3},
    "oak_log":         {"name": "Oak Log",          "emoji": "🌳", "value": 5},
    "maple_log":       {"name": "Maple Log",        "emoji": "🍁", "value": 8},
    "heartwood":       {"name": "Ancient Heartwood","emoji": "✨", "value": 40},
    # Hunter
    "rabbit":          {"name": "Rabbit",           "emoji": "🐇", "value": 5},
    "pelt":            {"name": "Pelt",             "emoji": "🦫", "value": 8},
    "venison":         {"name": "Venison",          "emoji": "🥩", "value": 10},
    "boar":            {"name": "Wild Boar",        "emoji": "🐗", "value": 22},
    # Baker
    "bread":           {"name": "Bread Loaf",       "emoji": "🍞", "value": 6},
    "meat_pie":        {"name": "Meat Pie",         "emoji": "🥧", "value": 10},
    "honey_cake":      {"name": "Honey Cake",       "emoji": "🍯", "value": 18},
    # Brewer
    "ale":             {"name": "Ale",              "emoji": "🍺", "value": 7},
    "mead":            {"name": "Mead",             "emoji": "🍶", "value": 12},
    "royal_wine":      {"name": "Royal Wine",       "emoji": "🍷", "value": 35},
    # Alchemist
    "herbs":           {"name": "Wild Herbs",       "emoji": "🌿", "value": 5},
    "minor_potion":    {"name": "Minor Potion",     "emoji": "🧪", "value": 16},
    "elixir":          {"name": "Golden Elixir",    "emoji": "⚗️", "value": 55},
}

# yields: (item_key, min_qty, max_qty, weight) — one entry is rolled per /work,
# weighted by the last number. cooldown is in seconds. tip is bonus coins.
JOBS = {
    "farmer": {
        "name": "Farmer", "emoji": "🌾", "cooldown": 60, "tip": (2, 6),
        "description": "Till the fields and bring in the harvest.",
        "yields": [
            ("wheat", 3, 7, 45), ("carrot", 2, 5, 30),
            ("apple", 2, 4, 18), ("pumpkin", 1, 2, 7),
        ],
        "flavour": [
            "You toil in the sun-baked fields from dawn till dusk.",
            "You swing your sickle through golden rows of grain.",
            "You dig through rich soil in the lord's back acres.",
            "A scarecrow watches as you gather the harvest.",
        ],
    },
    "miner": {
        "name": "Miner", "emoji": "⛏️", "cooldown": 60, "tip": (2, 6),
        "description": "Delve into the mountain for ore and gems.",
        "yields": [
            ("stone", 3, 8, 40), ("coal", 2, 6, 30),
            ("iron_ore", 2, 4, 20), ("gold_ore", 1, 2, 8), ("ruby", 1, 1, 2),
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
        "description": "Cast your line into river and sea.",
        "yields": [
            ("herring", 2, 6, 40), ("trout", 2, 4, 30),
            ("salmon", 1, 3, 20), ("pike", 1, 2, 8), ("royal_sturgeon", 1, 1, 2),
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
        "description": "Fell the great trees of the king's forest.",
        "yields": [
            ("birch_log", 3, 7, 45), ("oak_log", 2, 5, 32),
            ("maple_log", 1, 3, 20), ("heartwood", 1, 1, 3),
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
        "description": "Stalk game through wood and moor.",
        "yields": [
            ("rabbit", 1, 3, 38), ("pelt", 1, 3, 30),
            ("venison", 1, 2, 24), ("boar", 1, 1, 8),
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
        "description": "Fill the town square with the smell of fresh bread.",
        "yields": [
            ("bread", 2, 4, 50), ("meat_pie", 1, 3, 35), ("honey_cake", 1, 2, 15),
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
        "description": "Brew ale and mead for thirsty townsfolk.",
        "yields": [
            ("ale", 2, 4, 50), ("mead", 1, 3, 38), ("royal_wine", 1, 1, 12),
        ],
        "flavour": [
            "The tavern cellar bubbles with fresh barrels.",
            "You stir the mash and breathe in the sweet steam.",
            "A new batch of mead is ready for the tapping.",
            "The innkeeper pays well for your finest barrel.",
        ],
    },
    "alchemist": {
        "name": "Alchemist", "emoji": "🧪", "cooldown": 90, "tip": (4, 10),
        "description": "Brew potions and strange tinctures in your tower.",
        "yields": [
            ("herbs", 2, 5, 50), ("minor_potion", 1, 2, 38), ("elixir", 1, 1, 12),
        ],
        "flavour": [
            "Strange vapours curl from your bubbling cauldron.",
            "You grind rare herbs by candlelight in the tower.",
            "The mixture flashes green — a successful brew!",
            "You barter with a travelling herbalist for reagents.",
        ],
    },
}

# Tool tiers per job. Tier 0 (bare hands / basic kit) is free and implicit.
# Each entry: (display name, price in gold). Multiplier comes from TOOL_MULTIPLIERS.
TOOL_MULTIPLIERS = [1.0, 1.15, 1.30, 1.50]

TOOLS = {
    "farmer":     [("Iron Sickle", 300),      ("Steel Scythe", 1200),      ("Masterwork Scythe", 4000)],
    "miner":      [("Iron Pickaxe", 300),     ("Steel Pickaxe", 1200),     ("Dwarven Pickaxe", 4000)],
    "fisherman":  [("Oak Rod", 300),          ("Woven Net", 1200),         ("Royal Trawling Net", 4000)],
    "lumberjack": [("Iron Axe", 300),         ("Steel Felling Axe", 1200), ("Masterwork Greataxe", 4000)],
    "hunter":     [("Yew Shortbow", 350),     ("Composite Bow", 1300),     ("Elven Longbow", 4200)],
    "baker":      [("Stone Oven", 350),       ("Twin Brick Ovens", 1300),  ("Guild Bakehouse", 4200)],
    "brewer":     [("Copper Kettle", 350),    ("Oak Fermenters", 1400),    ("Guild Brewery", 4400)],
    "alchemist":  [("Glass Alembic", 400),    ("Silver Cauldron", 1500),   ("Philosopher's Still", 4600)],
}

BASE_TOOL_NAMES = {
    "farmer": "Rusty Sickle", "miner": "Worn Pickaxe", "fisherman": "Bent Rod",
    "lumberjack": "Chipped Axe", "hunter": "Old Sling", "baker": "Borrowed Hearth",
    "brewer": "Leaky Pot", "alchemist": "Cracked Flask",
}


def tool_name(job: str, tier: int) -> str:
    """Display name of the tool a player holds at the given tier."""
    if tier <= 0:
        return BASE_TOOL_NAMES[job]
    return TOOLS[job][tier - 1][0]


def tool_multiplier(tier: int) -> float:
    tier = max(0, min(tier, len(TOOL_MULTIPLIERS) - 1))
    return TOOL_MULTIPLIERS[tier]
