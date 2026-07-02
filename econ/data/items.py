"""Item registry. Add a new good here and it works everywhere:
inventories, the market, work yields, and sell autocomplete.

value  = base sell price in gold (the market drifts around it daily)
rarity = common | uncommon | rare | epic | legendary
"""

RARITIES = {
    "common":    {"name": "Common",    "badge": "▫️", "order": 0},
    "uncommon":  {"name": "Uncommon",  "badge": "🔹", "order": 1},
    "rare":      {"name": "Rare",      "badge": "🔷", "order": 2},
    "epic":      {"name": "Epic",      "badge": "🟣", "order": 3},
    "legendary": {"name": "Legendary", "badge": "🌟", "order": 4},
}

ITEMS = {
    # ── Farmer ──────────────────────────────────────────────────────────
    "wheat":          {"name": "Wheat",             "emoji": "🌾", "value": 3,  "rarity": "common"},
    "carrot":         {"name": "Carrot",            "emoji": "🥕", "value": 4,  "rarity": "common"},
    "apple":          {"name": "Apple",             "emoji": "🍎", "value": 6,  "rarity": "uncommon"},
    "pumpkin":        {"name": "Pumpkin",           "emoji": "🎃", "value": 14, "rarity": "rare"},
    "golden_apple":   {"name": "Golden Apple",      "emoji": "✨", "value": 60, "rarity": "legendary"},
    # ── Miner ───────────────────────────────────────────────────────────
    "stone":          {"name": "Stone",             "emoji": "🪨", "value": 2,  "rarity": "common"},
    "coal":           {"name": "Coal",              "emoji": "⚫", "value": 4,  "rarity": "common"},
    "iron_ore":       {"name": "Iron Ore",          "emoji": "⛓️", "value": 7,  "rarity": "uncommon"},
    "gold_ore":       {"name": "Gold Ore",          "emoji": "🟡", "value": 18, "rarity": "rare"},
    "ruby":           {"name": "Ruby",              "emoji": "💎", "value": 45, "rarity": "epic"},
    "dragon_gem":     {"name": "Dragonfire Gem",    "emoji": "🐉", "value": 90, "rarity": "legendary"},
    # ── Fisherman ───────────────────────────────────────────────────────
    "herring":        {"name": "Herring",           "emoji": "🐟", "value": 3,  "rarity": "common"},
    "trout":          {"name": "Trout",             "emoji": "🐠", "value": 6,  "rarity": "common"},
    "salmon":         {"name": "Salmon",            "emoji": "🍣", "value": 9,  "rarity": "uncommon"},
    "pike":           {"name": "Pike",              "emoji": "🦈", "value": 15, "rarity": "rare"},
    "royal_sturgeon": {"name": "Royal Sturgeon",    "emoji": "👑", "value": 50, "rarity": "epic"},
    "kraken_scale":   {"name": "Kraken Scale",      "emoji": "🐙", "value": 95, "rarity": "legendary"},
    # ── Lumberjack ──────────────────────────────────────────────────────
    "birch_log":      {"name": "Birch Log",         "emoji": "🪵", "value": 3,  "rarity": "common"},
    "oak_log":        {"name": "Oak Log",           "emoji": "🌳", "value": 5,  "rarity": "common"},
    "maple_log":      {"name": "Maple Log",         "emoji": "🍁", "value": 8,  "rarity": "uncommon"},
    "heartwood":      {"name": "Elder Heartwood", "emoji": "✨", "value": 40, "rarity": "epic"},
    "elderbark":      {"name": "Elderbark",         "emoji": "🌲", "value": 85, "rarity": "legendary"},
    # ── Hunter ──────────────────────────────────────────────────────────
    "rabbit":         {"name": "Rabbit",            "emoji": "🐇", "value": 5,  "rarity": "common"},
    "pelt":           {"name": "Pelt",              "emoji": "🦫", "value": 8,  "rarity": "uncommon"},
    "venison":        {"name": "Venison",           "emoji": "🥩", "value": 10, "rarity": "uncommon"},
    "boar":           {"name": "Wild Boar",         "emoji": "🐗", "value": 22, "rarity": "rare"},
    "white_stag":     {"name": "White Stag Horn", "emoji": "🦌", "value": 88, "rarity": "legendary"},
    # ── Baker ───────────────────────────────────────────────────────────
    "bread":          {"name": "Bread Loaf",        "emoji": "🍞", "value": 6,  "rarity": "common"},
    "meat_pie":       {"name": "Meat Pie",          "emoji": "🥧", "value": 10, "rarity": "uncommon"},
    "honey_cake":     {"name": "Honey Cake",        "emoji": "🍯", "value": 18, "rarity": "rare"},
    "kings_feast":    {"name": "King's Cake", "emoji": "👑", "value": 75, "rarity": "legendary"},
    # ── Brewer ──────────────────────────────────────────────────────────
    "ale":            {"name": "Ale",               "emoji": "🍺", "value": 7,  "rarity": "common"},
    "mead":           {"name": "Mead",              "emoji": "🍶", "value": 12, "rarity": "uncommon"},
    "royal_wine":     {"name": "Royal Wine",        "emoji": "🍷", "value": 35, "rarity": "epic"},
    "dwarven_stout":  {"name": "Dwarven Stout",     "emoji": "⚒️", "value": 80, "rarity": "legendary"},
    # ── Alchemist ───────────────────────────────────────────────────────
    "herbs":          {"name": "Wild Herbs",        "emoji": "🌿", "value": 5,  "rarity": "common"},
    "minor_potion":   {"name": "Minor Potion",      "emoji": "🧪", "value": 16, "rarity": "uncommon"},
    "elixir":         {"name": "Golden Elixir",     "emoji": "⚗️", "value": 55, "rarity": "epic"},
    "philosophers_dust": {"name": "Philosopher Dust", "emoji": "💫", "value": 110, "rarity": "legendary"},
    # ── Crafted Goods (see econ/data/recipes.py) ───────────────────────────
    "hearty_stew":            {"name": "Hearty Stew",             "emoji": "🍲", "value": 350,   "rarity": "uncommon"},
    "fishermans_basket":      {"name": "Fisherman's Basket",      "emoji": "🧺", "value": 380,   "rarity": "uncommon"},
    "reinforced_toolkit":     {"name": "Reinforced Toolkit",      "emoji": "🧰", "value": 1200,  "rarity": "rare"},
    "spiced_mead_cask":       {"name": "Spiced Mead Cask",        "emoji": "🛢️", "value": 1500,  "rarity": "rare"},
    "alchemical_tonic":       {"name": "Alchemical Tonic",        "emoji": "🔮", "value": 3000,  "rarity": "epic"},
    "huntsmans_cloak":        {"name": "Huntsman's Cloak",        "emoji": "🧥", "value": 3500,  "rarity": "epic"},
    "feast_of_kings":         {"name": "Feast of Kings",          "emoji": "🍗", "value": 7000,  "rarity": "legendary"},
    "dragonforged_blade":     {"name": "Dragonforged Blade",      "emoji": "⚔️", "value": 7500,  "rarity": "legendary"},
    "krakens_bounty":         {"name": "Kraken's Bounty",         "emoji": "🌊", "value": 15000, "rarity": "legendary"},
    "philosophers_masterwork": {"name": "Philosopher's Masterwork", "emoji": "🌟", "value": 20000, "rarity": "legendary"},
}


def item_label(item_key: str) -> str:
    info = ITEMS[item_key]
    return f"{info['emoji']} {info['name']}"


def rarity_badge(item_key: str) -> str:
    """Badge prefix for special finds. Common goods stay clean."""
    rarity = ITEMS[item_key]["rarity"]
    if RARITIES[rarity]["order"] < 2:
        return ""
    return RARITIES[rarity]["badge"] + " "
