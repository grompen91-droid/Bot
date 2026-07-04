"""Database-aware glue for the town system: reads towns/town_buildings/
town_workers rows and combines them with econ/data/town_buildings.py +
town_workers.py's registries into ready-to-use numbers. Kept separate
from formulas.py for the same reason buffs.py is -- this touches the
database, formulas.py stays pure math.
"""

from __future__ import annotations

from econ import formulas
from econ.data.town_buildings import TOWN_BUILDINGS, production_output_material
from econ.data.town_workers import TOWN_WORKERS, workers_for_building


async def get_building_tiers(db, guild_id: int, user_id: int) -> dict[str, int]:
    rows = await db.get_all_buildings(guild_id, user_id)
    return {row["building"]: row["tier"] for row in rows}


async def get_worker_tiers(db, guild_id: int, user_id: int) -> dict[str, int]:
    rows = await db.get_all_workers(guild_id, user_id)
    return {row["worker"]: row["tier"] for row in rows}


async def get_population(db, guild_id: int, user_id: int) -> int:
    """A real earned total, not derived from hall level/buildings/
    workers -- .expedition is the only thing that ever moves it (see
    Database.add_population)."""
    town = await db.get_town(guild_id, user_id)
    return town["population"] if town["hall_level"] > 0 else 0


async def town_bonus_totals(db, guild_id: int, user_id: int) -> dict[str, float]:
    """{"gold": x, "xp": x, "cooldown": x, "crit": x, "luck": x,
    "defense": x}, summed from every built bonus building plus its
    linked town-wide worker (if hired), plus a gold bonus from
    Population (earned via .expedition). An effect with nothing built
    simply isn't a key. Feeds
    formulas.apply_town_gold/xp/cooldown/crit/luck, stacked alongside
    coin_multiplier in cogs/jobs.py -- not through buffs.py's
    temporary-potion caps."""
    town = await db.get_town(guild_id, user_id)
    building_tiers = await get_building_tiers(db, guild_id, user_id)
    worker_tiers = await get_worker_tiers(db, guild_id, user_id)

    totals: dict[str, float] = {}
    for key, tier in building_tiers.items():
        info = TOWN_BUILDINGS.get(key)
        if not info or info["kind"] != "bonus" or tier <= 0:
            continue
        effect = info["effect"]
        totals[effect] = totals.get(effect, 0.0) + formulas.bonus_building_pct(effect, tier)

    for key, tier in worker_tiers.items():
        if tier <= 0:
            continue
        info = TOWN_WORKERS.get(key)
        building = TOWN_BUILDINGS.get(info["linked"]) if info else None
        if not building or building["kind"] != "bonus":
            continue
        effect = building["effect"]
        totals[effect] = totals.get(effect, 0.0) + formulas.townwide_worker_pct(effect, tier)

    if town["hall_level"] > 0 and town["population"] > 0:
        totals["gold"] = totals.get("gold", 0.0) + formulas.population_gold_bonus(town["population"])
    return totals


async def _linked_worker_tier(db, guild_id: int, user_id: int, building_key: str) -> int:
    """Sum of every worker linked to one building's tiers (a production
    building can have two hires; formulas.building_output_rate treats
    this as one combined "worker_tier" boosting the rate)."""
    total = 0
    for worker_key in workers_for_building(building_key):
        total += await db.get_worker_tier(guild_id, user_id, worker_key)
    return total


async def collectible_amount(
    db, guild_id: int, user_id: int, building_key: str, now: float,
) -> int:
    """How much a single built production building has accrued since
    it was last collected, without collecting it -- used for previews
    in .town/.buildings before committing to `.collect`."""
    info = TOWN_BUILDINGS[building_key]
    if info["kind"] != "production":
        return 0
    tier = await db.get_building_tier(guild_id, user_id, building_key)
    if tier <= 0:
        return 0
    last_collected = await db.get_last_collected(guild_id, user_id, building_key)
    if last_collected <= 0:
        return 0
    worker_tier = await _linked_worker_tier(db, guild_id, user_id, building_key)
    storehouse_tier = await db.get_building_tier(guild_id, user_id, "storehouse")
    elapsed = max(0.0, now - last_collected)
    return formulas.building_collect(
        info["base_rate"], info["base_cap"], tier, worker_tier, storehouse_tier, elapsed,
    )


async def collect_all(db, guild_id: int, user_id: int, now: float) -> dict[str, int]:
    """Collect every built production building's pending output into
    the satchel, resetting each one's clock. Returns {material: qty}
    for whatever actually came in; buildings with nothing accrued yet
    are simply absent from the result."""
    building_tiers = await get_building_tiers(db, guild_id, user_id)
    collected: dict[str, int] = {}
    for key, tier in building_tiers.items():
        info = TOWN_BUILDINGS.get(key)
        if not info or info["kind"] != "production" or tier <= 0:
            continue
        qty = await collectible_amount(db, guild_id, user_id, key, now)
        if qty <= 0:
            continue
        material_key = production_output_material(key, tier)
        await db.add_item(guild_id, user_id, material_key, qty)
        collected[material_key] = collected.get(material_key, 0) + qty
        await db.set_last_collected(guild_id, user_id, key, now)
    return collected


async def hired_worker_slots_used(db, guild_id: int, user_id: int) -> tuple[int, int]:
    """(used, capacity) hire slots -- capacity comes from the Workers'
    Lodge's own tier (0 if it isn't built, which is what keeps
    `.workers` gated entirely on that building existing)."""
    lodge_tier = await db.get_building_tier(guild_id, user_id, "workers_lodge")
    capacity = formulas.worker_slots(lodge_tier)
    used = await db.count_hired_workers(guild_id, user_id)
    return used, capacity
