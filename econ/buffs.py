"""Shared helper for reading a player's active consumable buffs and
turning them into ready-to-use multipliers. Used by any command that
wants to respect cooldown/XP/gold buffs (.work, .craft, ...).

Kept separate from formulas.py because it touches the database (reads
active_buffs); formulas.py stays pure math.
"""

from __future__ import annotations

import time

from econ.data.consumables import CONSUMABLES

# A cooldown buff can never make an action free; this caps the total
# reduction even if several cooldown buffs somehow stack at once.
MAX_COOLDOWN_REDUCTION = 0.75


async def active_buff_totals(db, guild_id: int, user_id: int) -> dict[str, float]:
    """Returns {"cooldown": total_magnitude, "xp": ..., "gold": ...},
    summed across every currently-active buff of that effect type.
    An effect with nothing active simply isn't a key (treat as 0)."""
    rows = await db.get_active_buffs(guild_id, user_id, time.time())
    totals: dict[str, float] = {}
    for row in rows:
        info = CONSUMABLES.get(row["item"])
        if not info:
            continue
        totals[info["effect"]] = totals.get(info["effect"], 0.0) + info["magnitude"]
    return totals


def apply_cooldown_buff(base_cooldown: float, totals: dict[str, float]) -> float:
    reduction = min(MAX_COOLDOWN_REDUCTION, totals.get("cooldown", 0.0))
    return base_cooldown * (1.0 - reduction)


def apply_xp_buff(base_xp: float, totals: dict[str, float]) -> float:
    return base_xp * (1.0 + totals.get("xp", 0.0))


def apply_gold_buff(base_gold: float, totals: dict[str, float]) -> float:
    return base_gold * (1.0 + totals.get("gold", 0.0))


def active_buff_summary(totals: dict[str, float]) -> str | None:
    """A short, single-line footer note, e.g. '-15% cooldown · +30% XP'.
    None if nothing is active, so callers can skip the line entirely."""
    labels = {"cooldown": "cooldown", "xp": "XP", "gold": "gold"}
    bits = []
    for effect in ("cooldown", "xp", "gold"):
        if effect in totals:
            sign = "-" if effect == "cooldown" else "+"
            bits.append(f"{sign}{round(totals[effect] * 100)}% {labels[effect]}")
    return " · ".join(bits) if bits else None
