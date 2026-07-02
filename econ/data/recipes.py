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
recipe, growing steeper at higher tiers (tier 1 is roughly an 18x
markup, the top tier nearly 50x). Crafting always mints the actual
output item into your satchel, never gold directly; .market and
.recipes show its market value just so you know what it's worth
before you sell it.
"""

from .items import ITEMS

RECIPES = {
    "hearty_stew": {
        "name": "Hearty Stew", "output_item": "hearty_stew",
        "ingredients": [("wheat", 3), ("venison", 1)],
        "unlock_level": 1,
    },
    "fishermans_basket": {
        "name": "Fisherman's Basket", "output_item": "fishermans_basket",
        "ingredients": [("herring", 3), ("bread", 2)],
        "unlock_level": 1,
    },
    "reinforced_toolkit": {
        "name": "Reinforced Toolkit", "output_item": "reinforced_toolkit",
        "ingredients": [("stone", 4), ("iron_ore", 2), ("oak_log", 2)],
        "unlock_level": 15,
    },
    "spiced_mead_cask": {
        "name": "Spiced Mead Cask", "output_item": "spiced_mead_cask",
        "ingredients": [("mead", 3), ("honey_cake", 2), ("maple_log", 1)],
        "unlock_level": 15,
    },
    "alchemical_tonic": {
        "name": "Alchemical Tonic", "output_item": "alchemical_tonic",
        "ingredients": [("herbs", 3), ("minor_potion", 2), ("ruby", 1)],
        "unlock_level": 30,
    },
    "huntsmans_cloak": {
        "name": "Huntsman's Cloak", "output_item": "huntsmans_cloak",
        "ingredients": [("pelt", 4), ("boar", 2), ("elixir", 1)],
        "unlock_level": 30,
    },
    "feast_of_kings": {
        "name": "Feast of Kings", "output_item": "feast_of_kings",
        "ingredients": [("kings_feast", 1), ("royal_wine", 1), ("white_stag", 1)],
        "unlock_level": 50,
    },
    "dragonforged_blade": {
        "name": "Dragonforged Blade", "output_item": "dragonforged_blade",
        "ingredients": [("dragon_gem", 1), ("iron_ore", 5), ("heartwood", 2)],
        "unlock_level": 50,
    },
    "krakens_bounty": {
        "name": "Kraken's Bounty", "output_item": "krakens_bounty",
        "ingredients": [("kraken_scale", 1), ("royal_sturgeon", 2), ("philosophers_dust", 1)],
        "unlock_level": 75,
    },
    "philosophers_masterwork": {
        "name": "Philosopher's Masterwork", "output_item": "philosophers_masterwork",
        "ingredients": [("philosophers_dust", 2), ("elixir", 2), ("dragon_gem", 1)],
        "unlock_level": 75,
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
