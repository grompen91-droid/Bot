"""Shared helper for reading a player's active consumable buffs and
turning them into ready-to-use multipliers. Used by any command that
wants to respect cooldown/XP/gold buffs -- .work, .craft, .brew,
.venture, .daily, .beg, .pickpocket, .smuggle, .rob, and every
per-job minigame all read through here.

Kept separate from formulas.py because it touches the database (reads
active_buffs); formulas.py stays pure math.

Same item used twice EXTENDS the remaining duration rather than
resetting it to a fresh copy (see extend_expiry), capped at
MAX_STACK_MULTIPLIER x its base duration so re-upping a cheap item
over and over can't buy a near-permanent buff. Different items of the
same effect (e.g. two different gold potions) stack additively, which
is why the totals below are capped too -- every gold item at once
would otherwise be a +130% multiplier with no ceiling.
"""

from __future__ import annotations

import time

from econ.data.consumables import CONSUMABLES

# A cooldown buff can never make an action free; this caps the total
# reduction even if several cooldown buffs somehow stack at once.
MAX_COOLDOWN_REDUCTION = 0.75
# Gold/XP have no natural floor like cooldown does, so they need their
# own caps to keep stacking every gold (or every XP) item at once from
# turning into a several-x multiplier.
MAX_GOLD_BONUS = 0.75
MAX_XP_BONUS = 1.00
# Re-using an already-active item extends it, but only up to this many
# times its own base duration -- past that, using another copy of the
# same item is just wasted.
MAX_STACK_MULTIPLIER = 3


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
    bonus = min(MAX_XP_BONUS, totals.get("xp", 0.0))
    return base_xp * (1.0 + bonus)


def apply_gold_buff(base_gold: float, totals: dict[str, float]) -> float:
    bonus = min(MAX_GOLD_BONUS, totals.get("gold", 0.0))
    return base_gold * (1.0 + bonus)


def active_buff_summary(totals: dict[str, float]) -> str | None:
    """A short, single-line footer note, e.g. '-15% cooldown · +30% XP'.
    None if nothing is active, so callers can skip the line entirely.
    Shows the (possibly capped) effective bonus, not the raw sum."""
    caps = {"cooldown": MAX_COOLDOWN_REDUCTION, "xp": MAX_XP_BONUS, "gold": MAX_GOLD_BONUS}
    labels = {"cooldown": "cooldown", "xp": "XP", "gold": "gold"}
    bits = []
    for effect in ("cooldown", "xp", "gold"):
        if effect in totals:
            value = min(caps[effect], totals[effect])
            sign = "-" if effect == "cooldown" else "+"
            capped = " (capped)" if totals[effect] > caps[effect] else ""
            bits.append(f"{sign}{round(value * 100)}% {labels[effect]}{capped}")
    return " · ".join(bits) if bits else None


def extend_expiry(current_expiry: float | None, item: str, now: float) -> float:
    """Using a consumable extends its remaining time rather than
    resetting it: an item with 10 minutes left, used again, gets its
    full duration added on top, not just reset back to a flat "full
    duration from now." Capped at MAX_STACK_MULTIPLIER x the item's own
    base duration, measured from now, so it can't be chained forever."""
    duration = CONSUMABLES[item]["duration"]
    base = current_expiry if current_expiry and current_expiry > now else now
    extended = base + duration
    cap = now + duration * MAX_STACK_MULTIPLIER
    return min(extended, cap)
