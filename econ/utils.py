"""Shared helpers: XP curves, market prices, formatting."""

import random
from datetime import date

from .jobs import ITEMS

GOLD = "🪙"


def fmt_gold(amount: int) -> str:
    return f"{amount:,} {GOLD}"


# -- skill progression -------------------------------------------------------

def xp_needed(level: int) -> int:
    """XP required to advance from `level` to `level + 1`."""
    return 80 + (level - 1) * 45


def apply_xp(level: int, xp: int, gained: int) -> tuple[int, int, int]:
    """Return (new_level, new_xp, levels_gained) after adding `gained` XP."""
    xp += gained
    start = level
    while xp >= xp_needed(level):
        xp -= xp_needed(level)
        level += 1
    return level, xp, level - start


def level_multiplier(level: int) -> float:
    """Yield bonus from skill: +3% per level past 1."""
    return 1.0 + (level - 1) * 0.03


def progress_bar(current: int, needed: int, width: int = 10) -> str:
    filled = int(width * min(current / needed, 1.0)) if needed else width
    return "█" * filled + "░" * (width - filled)


# -- market ------------------------------------------------------------------

def market_price(item: str, on: date | None = None) -> int:
    """Today's sell price for an item — base value with a daily seeded swing."""
    on = on or date.today()
    rng = random.Random(f"{on.isoformat()}:{item}")
    factor = rng.uniform(0.85, 1.20)
    return max(1, round(ITEMS[item]["value"] * factor))


def item_label(item: str) -> str:
    info = ITEMS[item]
    return f"{info['emoji']} {info['name']}"
