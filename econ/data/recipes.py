"""Recipe registry: combine gathered goods into a single, higher-value
crafted item. Add a recipe here (plus its output item in items.py) and
.craft/.recipes pick it up automatically.

Gated by a standalone Crafting skill, not tied to any trade -- anyone
can craft regardless of their current job, levelled by crafting
itself. unlock_level is the Crafting skill level required to attempt
the recipe. ingredients is a list of (item_key, qty), all consumed on
a successful craft; output_item is minted x1 in return.

Every recipe here prices its output far above the combined market
value of its ingredients -- a serious payout for actually finishing a
recipe. Ingredient quantities are tuned so that markup stays in a
roughly 5x-10x range regardless of tier: the moment a shop-sold
consumable's own price goes up (see econ/data/store.py's markup), the
gap between "cheap to craft" and "expensive to buy" widens right
along with it, and a recipe whose ingredients cost a trivial fraction
of its mint value turns crafting-then-reselling into free money (this
happened for real: Fisherman's Basket cost ~21 gold in herring/bread
and minted a 2,750 gold item). So the highest-markup offenders get
the biggest quantity bump, not a flat multiplier -- ingredient cost
is meant to track sale value, not just recipe tier. XP-buff recipes
also sit a tier above a cooldown/gold recipe of the same rank to
unlock: an XP buff is a direct shortcut on every trade's own grind.
Crafting always mints the actual output item into your satchel, never
gold directly; .market and .recipes show its market value just so you
know what it's worth before you sell it.
"""

from .items import ITEMS

RECIPES = {
    "hearty_stew": {
        "name": "Hearty Stew", "output_item": "hearty_stew",
        "ingredients": [("wheat", 15), ("venison", 5)],
        "unlock_level": 1,
    },
    "sip_of_insight": {
        "name": "Sip of Insight", "output_item": "sip_of_insight",
        "ingredients": [("herbs", 15), ("minor_potion", 5)],
        "unlock_level": 1,
    },
    "reinforced_toolkit": {
        "name": "Reinforced Toolkit", "output_item": "reinforced_toolkit",
        "ingredients": [("stone", 20), ("iron_ore", 10), ("oak_log", 10)],
        "unlock_level": 2,
    },
    "spiced_mead_cask": {
        "name": "Spiced Mead Cask", "output_item": "spiced_mead_cask",
        "ingredients": [("mead", 15), ("honey_cake", 10), ("maple_log", 5)],
        "unlock_level": 2,
    },
    "scholars_draught": {
        "name": "Scholar's Draught", "output_item": "scholars_draught",
        "ingredients": [("herbs", 10), ("minor_potion", 10), ("bread", 15)],
        "unlock_level": 2,
    },
    "huntsmans_cloak": {
        "name": "Huntsman's Cloak", "output_item": "huntsmans_cloak",
        "ingredients": [("pelt", 20), ("boar", 10), ("elixir", 5)],
        "unlock_level": 3,
    },
    "fishermans_basket": {
        "name": "Fisherman's Basket", "output_item": "fishermans_basket",
        "ingredients": [("herring", 48), ("bread", 32)],
        "unlock_level": 3,
    },
    "feast_of_kings": {
        "name": "Feast of Kings", "output_item": "feast_of_kings",
        "ingredients": [("kings_feast", 5), ("royal_wine", 5), ("white_stag", 5)],
        "unlock_level": 4,
    },
    "dragonforged_blade": {
        "name": "Dragonforged Blade", "output_item": "dragonforged_blade",
        "ingredients": [("dragon_gem", 5), ("iron_ore", 25), ("heartwood", 10)],
        "unlock_level": 4,
    },
    "sages_elixir": {
        "name": "Sage's Elixir", "output_item": "sages_elixir",
        "ingredients": [("minor_potion", 18), ("elixir", 6), ("honey_cake", 12)],
        "unlock_level": 4,
    },
    "krakens_bounty": {
        "name": "Kraken's Bounty", "output_item": "krakens_bounty",
        "ingredients": [("kraken_scale", 5), ("royal_sturgeon", 10), ("philosophers_dust", 5)],
        "unlock_level": 5,
    },
    "philosophers_masterwork": {
        "name": "Philosopher's Masterwork", "output_item": "philosophers_masterwork",
        "ingredients": [("philosophers_dust", 10), ("elixir", 10), ("dragon_gem", 5)],
        "unlock_level": 5,
    },
    "alchemical_tonic": {
        "name": "Alchemical Tonic", "output_item": "alchemical_tonic",
        "ingredients": [("herbs", 36), ("minor_potion", 24), ("ruby", 12)],
        "unlock_level": 5,
    },
}

# Registry sanity: every ingredient and output must reference a real item.
for _key, _r in RECIPES.items():
    if _r["output_item"] not in ITEMS:
        raise RuntimeError(f"Recipe {_key!r} outputs unknown item {_r['output_item']!r}")
    for _item, _qty in _r["ingredients"]:
        if _item not in ITEMS:
            raise RuntimeError(f"Recipe {_key!r} needs unknown item {_item!r}")

MAX_RECIPE_UNLOCK_LEVEL = max(r["unlock_level"] for r in RECIPES.values())


def resolve_recipe(query: str) -> str | None:
    """Fuzzy-match a user-typed recipe name ('hearty stew', 'toolkit')."""
    q = query.strip().lower()
    key_form = q.replace(" ", "_").replace("'", "")
    if key_form in RECIPES:
        return key_form
    for key, r in RECIPES.items():
        if r["name"].lower() == q:
            return key
    for key, r in RECIPES.items():
        if r["name"].lower().startswith(q) or key.startswith(key_form):
            return key
    return None
