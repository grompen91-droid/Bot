"""Town building registry: 16 buildings for the mid-game settlement
layer (see econ/formulas.py's "the town" section for the cost/output
math, and cogs/town.py for the UI). Each has 5 tiers; tier 0 means "not
built yet," tier 1 is the initial build, tiers 2-5 are upgrades.

kind:
  production - passively generates its linked material group over real
               time, capped storage, collected with `.town`/`.collect`.
  utility    - Workers' Lodge (gates `.workers`, raises hire capacity)
               and Storehouse (raises every production building's cap).
  bonus      - a permanent town-wide multiplier (gold/XP/cooldown/
               crit/bonus-find luck/crime defense), stacked in
               alongside coin_multiplier, not through buffs.py's
               temporary-potion caps.

Materials for production buildings come from their own group in
materials.py's MATERIAL_GROUPS (tier N draws that group's rarity-N
pair); utility/bonus buildings draw from the shared "universal" group
instead, since they aren't tied to one resource.
"""

from .. import formulas
from ..formulas import building_tier_cost
from .materials import MATERIAL_GROUPS


def _group_material(group: str, tier: int, slot: int = 0) -> str:
    """A production building's tier N draws from its own group:
    MATERIAL_GROUPS lists two items per rarity, tier 1..5 mapping onto
    common..legendary in order."""
    return MATERIAL_GROUPS[group][(tier - 1) * 2 + slot]


def _universal_material(tier: int, slot: int) -> str:
    """Same idea for utility/bonus buildings, drawing from the shared
    20-item "universal" group (four items per rarity) instead of a
    dedicated production group."""
    return MATERIAL_GROUPS["universal"][(tier - 1) * 4 + (slot % 4)]


def _tiers(
    base_gold: int, base_qty: int, material_fn, *, bonus: bool = False,
) -> list[tuple[int, dict[str, int]]]:
    """`bonus=True` (Guild Hall/Great Library/Town Square/Tavern/Temple/
    Watchtower) uses the steeper BONUS_BUILDING_GOLD_GROWTH curve
    instead of the standard one -- see formulas.py's back-loaded %
    section for why these six specifically cost more to fully climb."""
    tiers = []
    for tier in range(1, 6):
        if bonus:
            gold, qty = formulas.tier_cost(
                base_gold, base_qty, tier,
                gold_growth=formulas.BONUS_BUILDING_GOLD_GROWTH,
                qty_growth=formulas.BUILDING_MATERIAL_QTY_GROWTH,
            )
        else:
            gold, qty = building_tier_cost(base_gold, base_qty, tier)
        tiers.append((gold, {material_fn(tier): qty}))
    return tiers


_RAW_BUILDINGS = [
    # ── production: passive material income, gated by hall level ───────
    dict(key="quarry", name="Quarry", emoji="🪨", unlock_hall_level=1,
         kind="production", material_group="quarry", base_rate=8, base_cap=200,
         base_gold=4_000, base_qty=10,
         flavor="Blasts stone from the hillside day and night."),
    dict(key="sawmill", name="Sawmill", emoji="🪵", unlock_hall_level=1,
         kind="production", material_group="sawmill", base_rate=8, base_cap=200,
         base_gold=4_000, base_qty=10,
         flavor="Felled trunks become planks without you lifting an axe."),
    dict(key="brickworks", name="Brickworks", emoji="🧱", unlock_hall_level=2,
         kind="production", material_group="brickworks", base_rate=6, base_cap=180,
         base_gold=8_000, base_qty=12,
         flavor="Kilns fire clay into brick around the clock."),
    dict(key="foundry", name="Foundry", emoji="⛏️", unlock_hall_level=2,
         kind="production", material_group="foundry", base_rate=6, base_cap=180,
         base_gold=10_000, base_qty=12,
         flavor="Smelts raw ore into ingots ready for building."),
    dict(key="herb_garden", name="Herb Garden", emoji="🌿", unlock_hall_level=3,
         kind="production", material_group="herb_garden", base_rate=5, base_cap=150,
         base_gold=16_000, base_qty=15,
         flavor="Tended beds of reagents for the alchemists to come."),
    dict(key="weavers_yard", name="Weaver's Yard", emoji="🧵", unlock_hall_level=3,
         kind="production", material_group="weavers_yard", base_rate=5, base_cap=150,
         base_gold=18_000, base_qty=15,
         flavor="Looms clatter from dawn to dusk, spinning cloth."),
    dict(key="masons_workshop", name="Mason's Workshop", emoji="🏺", unlock_hall_level=4,
         kind="production", material_group="masons_workshop", base_rate=4, base_cap=120,
         base_gold=30_000, base_qty=18,
         flavor="Chisels turn stone into ornament fit for a hall."),
    dict(key="gem_cutters_den", name="Gem Cutter's Den", emoji="💎", unlock_hall_level=5,
         kind="production", material_group="gem_cutters_den", base_rate=3, base_cap=100,
         base_gold=50_000, base_qty=20,
         flavor="Slow, careful work -- but nothing sparkles like it."),

    # ── utility: gate/scale the rest of the system ──────────────────────
    dict(key="workers_lodge", name="Workers' Lodge", emoji="🏚️", unlock_hall_level=1,
         kind="utility", effect="worker_slots", base_gold=6_000, base_qty=10,
         flavor="Bunks and a warm meal -- without it, nobody stays to work."),
    dict(key="storehouse", name="Storehouse", emoji="📦", unlock_hall_level=2,
         kind="utility", effect="storage_cap", base_gold=12_000, base_qty=12,
         flavor="Bigger cellars mean less spoiling before you collect it."),

    # ── bonus: permanent, town-wide, stacks outside buffs.py's caps ─────
    dict(key="guild_hall", name="Guild Hall", emoji="🏛️", unlock_hall_level=2,
         kind="bonus", effect="gold", base_gold=14_000, base_qty=12,
         flavor="A charter and a ledger -- every deal in town pays a little better."),
    dict(key="great_library", name="Great Library", emoji="📚", unlock_hall_level=3,
         kind="bonus", effect="xp", base_gold=20_000, base_qty=15,
         flavor="Shelves of technique, free for any townsfolk to study."),
    dict(key="town_square", name="Town Square", emoji="⛲", unlock_hall_level=4,
         kind="bonus", effect="cooldown", base_gold=28_000, base_qty=18,
         flavor="Wider roads, shorter errands -- everything moves faster."),
    dict(key="tavern", name="Tavern", emoji="🍺", unlock_hall_level=4,
         kind="bonus", effect="crit", base_gold=28_000, base_qty=18,
         flavor="A round on the house puts a little swagger in every swing."),
    dict(key="temple", name="Temple", emoji="⛪", unlock_hall_level=6,
         kind="bonus", effect="luck", base_gold=62_000, base_qty=22,
         flavor="A quiet blessing before the day's work -- fortune favours you."),
    dict(key="watchtower", name="Watchtower", emoji="🗼", unlock_hall_level=6,
         kind="bonus", effect="defense", base_gold=62_000, base_qty=22,
         flavor="Eyes on the road keep thieves and misfortune at bay."),
]

TOWN_BUILDINGS: dict[str, dict] = {}
_utility_bonus_slot = 0
for _b in _RAW_BUILDINGS:
    _entry = dict(_b)
    if _entry["kind"] == "production":
        _entry["material_slot"] = 0
        _group = _entry["material_group"]
        _entry["tiers"] = _tiers(
            _entry["base_gold"], _entry["base_qty"],
            lambda tier, g=_group: _group_material(g, tier, 0),
        )
    else:
        _slot = _utility_bonus_slot
        _utility_bonus_slot += 1
        _entry["material_slot"] = _slot
        _entry["tiers"] = _tiers(
            _entry["base_gold"], _entry["base_qty"],
            lambda tier, s=_slot: _universal_material(tier, s),
            bonus=(_entry["kind"] == "bonus"),
        )
    TOWN_BUILDINGS[_entry["key"]] = _entry

MAX_BUILDING_TIER = 5
BUILDING_UNLOCK_ORDER = list(TOWN_BUILDINGS.keys())

assert len(TOWN_BUILDINGS) == 16, f"expected 16 buildings, got {len(TOWN_BUILDINGS)}"
assert sum(1 for b in TOWN_BUILDINGS.values() if b["kind"] == "production") == 8
assert sum(1 for b in TOWN_BUILDINGS.values() if b["kind"] == "bonus") == 6
assert sum(1 for b in TOWN_BUILDINGS.values() if b["kind"] == "utility") == 2


def building_tier_price(key: str, tier: int) -> tuple[int, dict[str, int]]:
    """(gold, {material: qty}) to reach `tier` (1..MAX_BUILDING_TIER)."""
    return TOWN_BUILDINGS[key]["tiers"][tier - 1]


def production_output_material(key: str, tier: int) -> str:
    """What a production building yields at its current tier -- the
    same material its own build cost drew from at that tier (slot 0 of
    its group), so upgrading also upgrades the QUALITY of what it
    produces, not just how much."""
    info = TOWN_BUILDINGS[key]
    return _group_material(info["material_group"], tier, 0)


def town_hall_material(level: int) -> str:
    """The material Town Hall's own ladder spends at `level` (2..9):
    draws from the shared universal group, rarity rising with level
    (levels 6-9 all draw legendary-tier stock, since there are more
    hall levels than rarities)."""
    n = max(0, level - 2)
    rarity_idx = min(4, n)
    return MATERIAL_GROUPS["universal"][rarity_idx * 4 + (n % 4)]
