"""Town worker registry: 20 hires for the mid-game settlement layer.
Each worker has 5 tiers (0 = not hired) and is `linked` to exactly one
building in town_buildings.py -- a production building's workers boost
its output rate, a bonus/utility building's worker boosts its effect
magnitude (econ/town.py combines the tiers into the final numbers).

Hiring at all requires the Workers' Lodge built (formulas.worker_slots
caps how many can be hired at once). Costs draw from the same material
group/rarity as the linked building, but a different concrete item
(production: slot 1, vs. the building's own slot 0; utility/bonus: one
slot over from the building's own universal slot), so a worker's
upgrade material is thematically related but never literally the same
purchase as the building's own.
"""

from .. import formulas
from ..formulas import worker_tier_cost
from .materials import MATERIAL_GROUPS
from .town_buildings import TOWN_BUILDINGS


def _group_material(group: str, tier: int, slot: int) -> str:
    return MATERIAL_GROUPS[group][(tier - 1) * 2 + slot]


def _universal_material(tier: int, slot: int) -> str:
    return MATERIAL_GROUPS["universal"][(tier - 1) * 4 + (slot % 4)]


def _tiers(
    base_gold: int, base_qty: int, material_fn, *, bonus: bool = False,
) -> list[tuple[int, dict[str, int]]]:
    """`bonus=True` (the 4 town-wide hires: Town Crier/Scribe/Guard
    Captain/Steward) uses the steeper BONUS_WORKER_GOLD_GROWTH curve --
    see formulas.py's back-loaded % section."""
    tiers = []
    for tier in range(1, 6):
        if bonus:
            gold, qty = formulas.tier_cost(
                base_gold, base_qty, tier,
                gold_growth=formulas.BONUS_WORKER_GOLD_GROWTH,
                qty_growth=formulas.WORKER_MATERIAL_QTY_GROWTH,
            )
        else:
            gold, qty = worker_tier_cost(base_gold, base_qty, tier)
        tiers.append((gold, {material_fn(tier): qty}))
    return tiers


_RAW_WORKERS = [
    # ── two hires per production building, cheaper than the building
    #    itself since a worker is an incremental boost, not the
    #    prerequisite ──────────────────────────────────────────────────
    dict(key="quarryman", name="Quarryman", emoji="⛏️", linked="quarry",
         base_gold=2_000, base_qty=5, flavor="Swings a pick from sunup to sundown."),
    dict(key="blast_foreman", name="Blast Foreman", emoji="🧨", linked="quarry",
         base_gold=3_000, base_qty=6, flavor="Knows exactly how much powder is too much."),
    dict(key="woodcutter", name="Woodcutter", emoji="🪓", linked="sawmill",
         base_gold=2_000, base_qty=5, flavor="Never misses the same notch twice."),
    dict(key="sawyer", name="Sawyer", emoji="🪚", linked="sawmill",
         base_gold=3_000, base_qty=6, flavor="Turns rough trunks into true planks."),
    dict(key="brickmaker", name="Brickmaker", emoji="🧱", linked="brickworks",
         base_gold=4_000, base_qty=7, flavor="Packs the mould the same way every time."),
    dict(key="kiln_master", name="Kiln Master", emoji="🔥", linked="brickworks",
         base_gold=5_000, base_qty=8, flavor="Reads a kiln's heat like a book."),
    dict(key="ore_smelter", name="Ore Smelter", emoji="🔥", linked="foundry",
         base_gold=5_000, base_qty=8, flavor="The furnace never truly cools."),
    dict(key="blacksmiths_apprentice", name="Blacksmith's Apprentice", emoji="🔨", linked="foundry",
         base_gold=6_000, base_qty=8, flavor="Eager, and getting better by the week."),
    dict(key="herbalist", name="Herbalist", emoji="🌿", linked="herb_garden",
         base_gold=8_000, base_qty=9, flavor="Knows every plot by smell alone."),
    dict(key="greenhouse_keeper", name="Greenhouse Keeper", emoji="🪴", linked="herb_garden",
         base_gold=10_000, base_qty=10, flavor="Coaxes a second harvest out of tired soil."),
    dict(key="weaver", name="Weaver", emoji="🧵", linked="weavers_yard",
         base_gold=9_000, base_qty=9, flavor="The loom barely pauses for breath."),
    dict(key="dye_master", name="Dye Master", emoji="🎨", linked="weavers_yard",
         base_gold=11_000, base_qty=10, flavor="Colours that don't fade in the wash."),
    dict(key="mason", name="Mason", emoji="🪨", linked="masons_workshop",
         base_gold=13_000, base_qty=11, flavor="Squares every block before it's set."),
    dict(key="stonecarver", name="Stonecarver", emoji="🗿", linked="masons_workshop",
         base_gold=17_000, base_qty=12, flavor="Turns a plain block into a signature."),
    dict(key="gem_cutter", name="Gem Cutter", emoji="💎", linked="gem_cutters_den",
         base_gold=22_000, base_qty=14, flavor="One wrong tap ruins a week's work -- theirs never do."),
    dict(key="jewelers_apprentice", name="Jeweler's Apprentice", emoji="🔍", linked="gem_cutters_den",
         base_gold=27_000, base_qty=15, flavor="Learning the trade on the town's own stones."),

    # ── four town-wide hires, each boosting one bonus/utility building ──
    dict(key="town_crier", name="Town Crier", emoji="📯", linked="guild_hall",
         base_gold=15_000, base_qty=12, flavor="Talks up every deal before it's even struck."),
    dict(key="scribe", name="Scribe", emoji="✍️", linked="great_library",
         base_gold=18_000, base_qty=13, flavor="Copies down every lesson worth keeping."),
    dict(key="guard_captain", name="Guard Captain", emoji="🛡️", linked="watchtower",
         base_gold=30_000, base_qty=16, flavor="Nothing gets past the wall on their watch."),
    dict(key="steward", name="Steward", emoji="🗝️", linked="storehouse",
         base_gold=17_000, base_qty=12, flavor="Knows exactly what's in every crate and why."),
]

TOWN_WORKERS: dict[str, dict] = {}
for _w in _RAW_WORKERS:
    _entry = dict(_w)
    _building = TOWN_BUILDINGS[_entry["linked"]]
    if _building["kind"] == "production":
        _group = _building["material_group"]
        _entry["tiers"] = _tiers(
            _entry["base_gold"], _entry["base_qty"],
            lambda tier, g=_group: _group_material(g, tier, 1),  # slot 1: distinct from the building's own slot 0
        )
    else:
        _slot = (_building["material_slot"] + 1) % 4  # one over from the building's own universal slot
        _entry["tiers"] = _tiers(
            _entry["base_gold"], _entry["base_qty"],
            lambda tier, s=_slot: _universal_material(tier, s),
            bonus=True,
        )
    TOWN_WORKERS[_entry["key"]] = _entry

MAX_WORKER_TIER = 5

assert len(TOWN_WORKERS) == 20, f"expected 20 workers, got {len(TOWN_WORKERS)}"
for _w in TOWN_WORKERS.values():
    assert _w["linked"] in TOWN_BUILDINGS, f"worker {_w['key']!r} links to unknown building {_w['linked']!r}"


def worker_tier_price(key: str, tier: int) -> tuple[int, dict[str, int]]:
    """(gold, {material: qty}) to reach `tier` (1..MAX_WORKER_TIER)."""
    return TOWN_WORKERS[key]["tiers"][tier - 1]


def workers_for_building(building_key: str) -> list[str]:
    return [key for key, info in TOWN_WORKERS.items() if info["linked"] == building_key]
