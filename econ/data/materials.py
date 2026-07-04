"""Construction materials for the town system (econ/data/town_buildings.py,
town_workers.py, cogs/town.py). Same shape as items.py's ITEMS (name,
emoji, value, rarity) -- merged into ITEMS at the bottom of items.py so
every material gets inventory storage, .inventory/.market listings, and
sell-autocomplete for free, exactly like a trade good.

Grouped by the production building that yields it (see
town_buildings.py), plus a "universal" group spent across multiple
building types (and Town Hall's own ladder, which doesn't belong to any
one building). Each group spans the same five rarities as items.py so
higher building/worker tiers can demand rarer stock, not just more of
the same.
"""

import random

MATERIALS = {
    # ── Quarry: Stone family ───────────────────────────────────────────
    "rubble":          {"name": "Rubble",              "emoji": "🪨", "value": 4,   "rarity": "common"},
    "rough_stone":     {"name": "Rough Stone",          "emoji": "🪨", "value": 6,   "rarity": "common"},
    "cut_stone":       {"name": "Cut Stone",            "emoji": "🧱", "value": 14,  "rarity": "uncommon"},
    "slate_shingle":   {"name": "Slate Shingle",        "emoji": "🪨", "value": 18,  "rarity": "uncommon"},
    "granite_block":   {"name": "Granite Block",        "emoji": "🗿", "value": 55,  "rarity": "rare"},
    "flagstone":       {"name": "Flagstone",            "emoji": "🪨", "value": 65,  "rarity": "rare"},
    "marble_slab":     {"name": "Marble Slab",          "emoji": "⬜", "value": 220, "rarity": "epic"},
    "obsidian_block":  {"name": "Obsidian Block",       "emoji": "⬛", "value": 260, "rarity": "epic"},
    "skystone_block":  {"name": "Skystone Block",       "emoji": "🌫️", "value": 700, "rarity": "legendary"},
    "titans_cornerstone": {"name": "Titan's Cornerstone", "emoji": "🏔️", "value": 850, "rarity": "legendary"},

    # ── Sawmill: Timber family ──────────────────────────────────────────
    "green_timber":    {"name": "Green Timber",         "emoji": "🪵", "value": 4,   "rarity": "common"},
    "split_log":       {"name": "Split Log",            "emoji": "🪵", "value": 6,   "rarity": "common"},
    "seasoned_plank":  {"name": "Seasoned Plank",       "emoji": "📏", "value": 14,  "rarity": "uncommon"},
    "birch_board":     {"name": "Birch Board",          "emoji": "🪵", "value": 18,  "rarity": "uncommon"},
    "oak_beam":        {"name": "Oak Beam",             "emoji": "🪵", "value": 55,  "rarity": "rare"},
    "ironwood_plank":  {"name": "Ironwood Plank",       "emoji": "📏", "value": 65,  "rarity": "rare"},
    "heartwood_beam":  {"name": "Ancient Heartwood Beam", "emoji": "🌳", "value": 220, "rarity": "epic"},
    "silverwood_plank": {"name": "Silverwood Plank",    "emoji": "✨", "value": 260, "rarity": "epic"},
    "worldtree_bough": {"name": "World-Tree Bough",     "emoji": "🌲", "value": 700, "rarity": "legendary"},
    "phoenix_ash_timber": {"name": "Phoenix Ash Timber", "emoji": "🔥", "value": 850, "rarity": "legendary"},

    # ── Brickworks: Brick & Clay family ─────────────────────────────────
    "wet_clay":        {"name": "Wet Clay",             "emoji": "🟫", "value": 4,   "rarity": "common"},
    "fired_brick":     {"name": "Fired Brick",          "emoji": "🧱", "value": 6,   "rarity": "common"},
    "glazed_brick":    {"name": "Glazed Brick",         "emoji": "🧱", "value": 14,  "rarity": "uncommon"},
    "terracotta_tile": {"name": "Terracotta Tile",      "emoji": "🟧", "value": 18,  "rarity": "uncommon"},
    "reinforced_brick": {"name": "Reinforced Brick",    "emoji": "🧱", "value": 55,  "rarity": "rare"},
    "kilnfired_block": {"name": "Kiln-Fired Block",     "emoji": "🧱", "value": 65,  "rarity": "rare"},
    "runed_brick":     {"name": "Runed Brick",          "emoji": "🔶", "value": 220, "rarity": "epic"},
    "dragonclay_block": {"name": "Dragonclay Block",    "emoji": "🐉", "value": 260, "rarity": "epic"},
    "sunbaked_ember_brick": {"name": "Sunbaked Ember Brick", "emoji": "🔥", "value": 700, "rarity": "legendary"},
    "emberstone_block": {"name": "Emberstone Block",    "emoji": "🌋", "value": 850, "rarity": "legendary"},

    # ── Foundry: Ore & Ingot family ──────────────────────────────────────
    "scrap_iron":      {"name": "Scrap Iron",           "emoji": "🔩", "value": 4,   "rarity": "common"},
    "iron_ingot":      {"name": "Iron Ingot",           "emoji": "⛓️", "value": 6,   "rarity": "common"},
    "steel_ingot":     {"name": "Steel Ingot",          "emoji": "🔩", "value": 14,  "rarity": "uncommon"},
    "bronze_ingot":    {"name": "Bronze Ingot",         "emoji": "🟤", "value": 18,  "rarity": "uncommon"},
    "mithril_ingot":   {"name": "Mithril Ingot",        "emoji": "⚙️", "value": 55,  "rarity": "rare"},
    "cold_iron_ingot": {"name": "Cold Iron Ingot",      "emoji": "🔗", "value": 65,  "rarity": "rare"},
    "adamant_ingot":   {"name": "Adamant Ingot",        "emoji": "🔘", "value": 220, "rarity": "epic"},
    "starforged_ingot": {"name": "Starforged Ingot",    "emoji": "🌟", "value": 260, "rarity": "epic"},
    "dragonsteel_ingot": {"name": "Dragonsteel Ingot",  "emoji": "🐉", "value": 700, "rarity": "legendary"},
    "celestial_alloy": {"name": "Celestial Alloy",      "emoji": "☄️", "value": 850, "rarity": "legendary"},

    # ── Herb Garden: Herb & Reagent family ───────────────────────────────
    "dried_herbs":     {"name": "Dried Herbs",          "emoji": "🌿", "value": 4,   "rarity": "common"},
    "meadow_root":     {"name": "Meadow Root",          "emoji": "🌱", "value": 6,   "rarity": "common"},
    "sunpetal":        {"name": "Sunpetal",             "emoji": "🌼", "value": 14,  "rarity": "uncommon"},
    "moonleaf":        {"name": "Moonleaf",             "emoji": "🍃", "value": 18,  "rarity": "uncommon"},
    "silverthorn":     {"name": "Silverthorn",          "emoji": "🌵", "value": 55,  "rarity": "rare"},
    "witchbloom":      {"name": "Witchbloom",           "emoji": "🌺", "value": 65,  "rarity": "rare"},
    "ember_lotus":     {"name": "Ember Lotus",          "emoji": "🪷", "value": 220, "rarity": "epic"},
    "frostvine":       {"name": "Frostvine",            "emoji": "❄️", "value": 260, "rarity": "epic"},
    "worldroot_sprig": {"name": "Worldroot Sprig",      "emoji": "🌳", "value": 700, "rarity": "legendary"},
    "phoenix_bloom":   {"name": "Phoenix Bloom",        "emoji": "🔥", "value": 850, "rarity": "legendary"},

    # ── Weaver's Yard: Cloth & Textile family ────────────────────────────
    "rough_wool":      {"name": "Rough Wool",           "emoji": "🧶", "value": 4,   "rarity": "common"},
    "flax_thread":     {"name": "Flax Thread",          "emoji": "🧵", "value": 6,   "rarity": "common"},
    "woven_cloth":     {"name": "Woven Cloth",          "emoji": "🧵", "value": 14,  "rarity": "uncommon"},
    "dyed_linen":      {"name": "Dyed Linen",           "emoji": "🟦", "value": 18,  "rarity": "uncommon"},
    "silk_bolt":       {"name": "Silk Bolt",            "emoji": "🎀", "value": 55,  "rarity": "rare"},
    "velvet_roll":     {"name": "Velvet Roll",          "emoji": "🟣", "value": 65,  "rarity": "rare"},
    "enchanted_silk":  {"name": "Enchanted Silk",       "emoji": "✨", "value": 220, "rarity": "epic"},
    "shimmercloth":    {"name": "Shimmercloth",         "emoji": "🌈", "value": 260, "rarity": "epic"},
    "spidersilk_weave": {"name": "Spidersilk Weave",    "emoji": "🕸️", "value": 700, "rarity": "legendary"},
    "starwoven_tapestry": {"name": "Starwoven Tapestry", "emoji": "🌌", "value": 850, "rarity": "legendary"},

    # ── Mason's Workshop: Masonry & Ornamental family ────────────────────
    "chipped_tile":    {"name": "Chipped Tile",         "emoji": "▫️", "value": 4,   "rarity": "common"},
    "plaster_cast":    {"name": "Plaster Cast",         "emoji": "⬜", "value": 6,   "rarity": "common"},
    "carved_stonework": {"name": "Carved Stonework",    "emoji": "🗿", "value": 14,  "rarity": "uncommon"},
    "inlaid_tile":     {"name": "Inlaid Tile",          "emoji": "🔷", "value": 18,  "rarity": "uncommon"},
    "sculpted_frieze": {"name": "Sculpted Frieze",      "emoji": "🏛️", "value": 55,  "rarity": "rare"},
    "gilded_cornice":  {"name": "Gilded Cornice",       "emoji": "🟨", "value": 65,  "rarity": "rare"},
    "masterwork_statue": {"name": "Masterwork Statue",  "emoji": "🗽", "value": 220, "rarity": "epic"},
    "ornate_archway":  {"name": "Ornate Archway",       "emoji": "🏛️", "value": 260, "rarity": "epic"},
    "monument_centerpiece": {"name": "Monument Centerpiece", "emoji": "🏆", "value": 700, "rarity": "legendary"},
    "royal_facade":    {"name": "Royal Facade",         "emoji": "👑", "value": 850, "rarity": "legendary"},

    # ── Gem Cutter's Den: Gem & Crystal family ───────────────────────────
    "quartz_shard":    {"name": "Quartz Shard",         "emoji": "🔹", "value": 5,   "rarity": "common"},
    "rock_crystal":    {"name": "Rock Crystal",         "emoji": "🔹", "value": 7,   "rarity": "common"},
    "amethyst_shard":  {"name": "Amethyst Shard",       "emoji": "🟣", "value": 16,  "rarity": "uncommon"},
    "citrine_shard":   {"name": "Citrine Shard",        "emoji": "🟡", "value": 20,  "rarity": "uncommon"},
    "sapphire_shard":  {"name": "Sapphire Shard",       "emoji": "🔵", "value": 60,  "rarity": "rare"},
    "emerald_shard":   {"name": "Emerald Shard",        "emoji": "🟢", "value": 70,  "rarity": "rare"},
    "flawless_ruby":   {"name": "Flawless Ruby",        "emoji": "🔴", "value": 240, "rarity": "epic"},
    "void_opal":       {"name": "Void Opal",            "emoji": "⚫", "value": 280, "rarity": "epic"},
    "heart_of_the_mountain": {"name": "Heart of the Mountain", "emoji": "💎", "value": 750, "rarity": "legendary"},
    "starlight_diamond": {"name": "Starlight Diamond",  "emoji": "💠", "value": 900, "rarity": "legendary"},

    # ── Universal: spent across multiple buildings, and Town Hall itself ─
    "nails":           {"name": "Nails",                "emoji": "📌", "value": 5,   "rarity": "common"},
    "rope":            {"name": "Rope",                 "emoji": "🪢", "value": 6,   "rarity": "common"},
    "mortar":          {"name": "Mortar",                "emoji": "🪣", "value": 7,   "rarity": "common"},
    "pitch":           {"name": "Pitch",                "emoji": "🛢️", "value": 8,   "rarity": "common"},
    "iron_fittings":   {"name": "Iron Fittings",        "emoji": "🔧", "value": 20,  "rarity": "uncommon"},
    "reinforced_rope": {"name": "Reinforced Rope",      "emoji": "🪢", "value": 24,  "rarity": "uncommon"},
    "sealing_wax":     {"name": "Sealing Wax",          "emoji": "🕯️", "value": 26,  "rarity": "uncommon"},
    "tempered_nails":  {"name": "Tempered Nails",       "emoji": "📌", "value": 28,  "rarity": "uncommon"},
    "blueprint_scroll": {"name": "Blueprint Scroll",    "emoji": "📜", "value": 80,  "rarity": "rare"},
    "enchanted_hinge": {"name": "Enchanted Hinge",      "emoji": "🚪", "value": 90,  "rarity": "rare"},
    "masterwork_tools": {"name": "Masterwork Tools",    "emoji": "🛠️", "value": 100, "rarity": "rare"},
    "sturdy_scaffolding": {"name": "Sturdy Scaffolding", "emoji": "🪜", "value": 110, "rarity": "rare"},
    "enchanted_dust":  {"name": "Enchanted Dust",       "emoji": "✨", "value": 300, "rarity": "epic"},
    "runed_framework": {"name": "Runed Framework",      "emoji": "🔶", "value": 320, "rarity": "epic"},
    "arcane_blueprint": {"name": "Arcane Blueprint",    "emoji": "📘", "value": 340, "rarity": "epic"},
    "golden_fixtures": {"name": "Golden Fixtures",      "emoji": "🟨", "value": 360, "rarity": "epic"},
    "architects_masterplan": {"name": "Architect's Masterplan", "emoji": "📐", "value": 950, "rarity": "legendary"},
    "phoenix_feather_binding": {"name": "Phoenix Feather Binding", "emoji": "🪶", "value": 1000, "rarity": "legendary"},
    "crown_jewel_fitting": {"name": "Crown Jewel Fitting", "emoji": "👑", "value": 1050, "rarity": "legendary"},
    "heart_of_the_town": {"name": "Heart of the Town",  "emoji": "❤️", "value": 1100, "rarity": "legendary"},
}

# Registry sanity: no accidental key collision with an existing trade good.
assert len(MATERIALS) == 100, f"expected 100 materials, got {len(MATERIALS)}"

# Builder's Supply (cogs/town.py's `.supply`) markup over a material's
# base value -- pricier than the market's daily-drifting sell price,
# same "convenience costs extra" idea as .shop's STORE_RARE_MARKUP, and
# sold in bundles of 10 given how many units a building/worker tier
# tends to need.
MATERIAL_SUPPLY_MARKUP = 6.0
MATERIAL_SUPPLY_BUNDLE = 10

# .supply only bootstraps the cheap end of the ladder -- rare and above
# can't be bought at any price, they have to be earned: a production
# building's own passive trickle once it's already at that tier, the
# active `.gather` command (see formulas.py's "the town" section), or
# for the trade-agnostic "universal" group, a small work-drop chance
# from ordinary `.work` (see WORK_DROP_MATERIAL_CHANCE in formulas.py).
MATERIAL_SUPPLY_MAX_RARITY_ORDER = 1  # 0=common, 1=uncommon -- see RARITIES in items.py

# One material key per (group, rarity) -- used by town_buildings.py to
# reference "give me the rare tier of the Quarry's family" without
# hardcoding item keys everywhere.
MATERIAL_GROUPS = {
    "quarry": [
        "rubble", "rough_stone", "cut_stone", "slate_shingle",
        "granite_block", "flagstone", "marble_slab", "obsidian_block",
        "skystone_block", "titans_cornerstone",
    ],
    "sawmill": [
        "green_timber", "split_log", "seasoned_plank", "birch_board",
        "oak_beam", "ironwood_plank", "heartwood_beam", "silverwood_plank",
        "worldtree_bough", "phoenix_ash_timber",
    ],
    "brickworks": [
        "wet_clay", "fired_brick", "glazed_brick", "terracotta_tile",
        "reinforced_brick", "kilnfired_block", "runed_brick",
        "dragonclay_block", "sunbaked_ember_brick", "emberstone_block",
    ],
    "foundry": [
        "scrap_iron", "iron_ingot", "steel_ingot", "bronze_ingot",
        "mithril_ingot", "cold_iron_ingot", "adamant_ingot",
        "starforged_ingot", "dragonsteel_ingot", "celestial_alloy",
    ],
    "herb_garden": [
        "dried_herbs", "meadow_root", "sunpetal", "moonleaf",
        "silverthorn", "witchbloom", "ember_lotus", "frostvine",
        "worldroot_sprig", "phoenix_bloom",
    ],
    "weavers_yard": [
        "rough_wool", "flax_thread", "woven_cloth", "dyed_linen",
        "silk_bolt", "velvet_roll", "enchanted_silk", "shimmercloth",
        "spidersilk_weave", "starwoven_tapestry",
    ],
    "masons_workshop": [
        "chipped_tile", "plaster_cast", "carved_stonework", "inlaid_tile",
        "sculpted_frieze", "gilded_cornice", "masterwork_statue",
        "ornate_archway", "monument_centerpiece", "royal_facade",
    ],
    "gem_cutters_den": [
        "quartz_shard", "rock_crystal", "amethyst_shard", "citrine_shard",
        "sapphire_shard", "emerald_shard", "flawless_ruby", "void_opal",
        "heart_of_the_mountain", "starlight_diamond",
    ],
    "universal": [
        "nails", "rope", "mortar", "pitch",
        "iron_fittings", "reinforced_rope", "sealing_wax", "tempered_nails",
        "blueprint_scroll", "enchanted_hinge", "masterwork_tools", "sturdy_scaffolding",
        "enchanted_dust", "runed_framework", "arcane_blueprint", "golden_fixtures",
        "architects_masterplan", "phoenix_feather_binding", "crown_jewel_fitting",
        "heart_of_the_town",
    ],
}

for _group, _keys in MATERIAL_GROUPS.items():
    for _key in _keys:
        if _key not in MATERIALS:
            raise RuntimeError(f"MATERIAL_GROUPS[{_group!r}] references unknown material {_key!r}")

_RARITY_ORDER = ("common", "uncommon", "rare", "epic", "legendary")


def random_universal_material(rarity: str) -> str:
    """One of the 4 "universal" group materials at `rarity` -- the
    work-drop path for Town Hall's own ladder and the utility/bonus
    buildings, none of which are produced by any one building."""
    idx = _RARITY_ORDER.index(rarity)
    return random.choice(MATERIAL_GROUPS["universal"][idx * 4 : idx * 4 + 4])
