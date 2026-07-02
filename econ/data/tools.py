"""Tool registry: five purchasable tiers per trade (tier 0 is the free
battered starter tool). Yield multipliers per tier live in
econ/formulas.py (TOOL_MULTIPLIERS); names and prices live here.

Each list entry is (display_name, price) for tiers 1..5.
"""

from .jobs import JOBS

TOOL_PRICES = [300, 1_000, 3_200, 10_000, 30_000]

TOOLS = {
    "farmer": [
        "Iron Sickle", "Steel Scythe", "Oxen & Plough",
        "Master Scythe", "Holy Harvester",
    ],
    "miner": [
        "Iron Pickaxe", "Steel Pickaxe", "Blasting Powder",
        "Dwarven Pickaxe", "Earthbreaker",
    ],
    "fisherman": [
        "Oak Rod", "Woven Net", "River Skiff",
        "Royal Trawler", "Leviathan Hook",
    ],
    "lumberjack": [
        "Iron Axe", "Felling Axe", "Two-Man Saw",
        "Grand Greataxe", "Root Cleaver",
    ],
    "hunter": [
        "Yew Shortbow", "Composite Bow", "Hunting Hounds",
        "Elven Longbow", "Wyvernstring Bow",
    ],
    "baker": [
        "Stone Oven", "Twin Brick Ovens", "Mill Contract",
        "Guild Bakehouse", "Enchanted Hearth",
    ],
    "brewer": [
        "Copper Kettle", "Oak Fermenters", "Cellar Expansion",
        "Guild Brewery", "Everfull Cask",
    ],
    "alchemist": [
        "Glass Alembic", "Silver Cauldron", "Arcane Library",
        "Arcane Still", "Star Athanor",
    ],
    "criminal": [
        "Lockpick Set", "Forged Papers", "Smoke Bombs",
        "Guild Contact", "Shadow Cloak",
    ],
}

BASE_TOOL_NAMES = {
    "farmer": "Rusty Sickle", "miner": "Worn Pickaxe", "fisherman": "Bent Rod",
    "lumberjack": "Chipped Axe", "hunter": "Old Sling", "baker": "Borrowed Hearth",
    "brewer": "Leaky Pot", "alchemist": "Cracked Flask", "criminal": "Bare Hands",
}

MAX_TOOL_TIER = len(TOOL_PRICES)

# Registry sanity: every job needs a full tool ladder.
for _job_key in JOBS:
    if _job_key not in TOOLS or len(TOOLS[_job_key]) != MAX_TOOL_TIER:
        raise RuntimeError(f"Job {_job_key!r} needs {MAX_TOOL_TIER} tools in tools.py")
    if _job_key not in BASE_TOOL_NAMES:
        raise RuntimeError(f"Job {_job_key!r} needs a base tool name")


def tool_name(job_key: str, tier: int) -> str:
    if tier <= 0:
        return BASE_TOOL_NAMES[job_key]
    return TOOLS[job_key][min(tier, MAX_TOOL_TIER) - 1]


def tool_price(tier: int) -> int:
    """Price to buy tier `tier` (1-indexed)."""
    return TOOL_PRICES[tier - 1]
