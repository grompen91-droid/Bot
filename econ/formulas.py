"""Every tunable number and curve in the economy lives here.

Balance the whole game from this one file: XP pacing, yield scaling,
crit/luck odds, cooldowns, market drift, daily payouts, tool power.
All functions are pure (given the same inputs they return the same
outputs) except the ones that explicitly take/roll randomness.
"""

from __future__ import annotations

import math
import random
import zlib
from datetime import datetime, timezone

# ══════════════════════════════ currency ═══════════════════════════════

CURRENCY = "🪙"
STARTING_GOLD = 0


def fmt_gold(amount: int) -> str:
    return f"{amount:,} {CURRENCY}"


# ═══════════════════════════ skill XP curve ════════════════════════════
# Polynomial curve: cheap early levels, steadily steeper. At ~12 XP per
# work: level 2 in ~5 works, level 10 in ~45, level 25 in ~250.

XP_BASE = 60
XP_EXPONENT = 1.35
MAX_LEVEL = 100


def xp_to_next(level: int) -> int:
    """XP required to advance from `level` to `level + 1`."""
    return round(XP_BASE * level**XP_EXPONENT)


def apply_xp(level: int, xp: int, gained: int) -> tuple[int, int, int]:
    """Return (new_level, new_xp, levels_gained) after adding XP."""
    xp += gained
    start = level
    while level < MAX_LEVEL and xp >= xp_to_next(level):
        xp -= xp_to_next(level)
        level += 1
    if level >= MAX_LEVEL:
        xp = min(xp, xp_to_next(MAX_LEVEL))
    return level, xp, level - start


WORK_XP_MIN, WORK_XP_MAX = 9, 15


def roll_work_xp(cooldown: int) -> int:
    """XP per work. Slower trades pay more XP so all trades level fairly."""
    scale = (cooldown / 60) ** 0.75
    return max(1, round(random.randint(WORK_XP_MIN, WORK_XP_MAX) * scale))


# ═══════════════════════ yield & level scaling ═════════════════════════
# +3% yield per level up to the soft cap, +1% per level beyond it.
# Keeps early progress snappy without runaway inflation at high level.

YIELD_PER_LEVEL = 0.03
YIELD_SOFT_CAP = 25
YIELD_PER_LEVEL_AFTER_CAP = 0.01


def level_yield_multiplier(level: int) -> float:
    below = min(level - 1, YIELD_SOFT_CAP - 1)
    above = max(level - YIELD_SOFT_CAP, 0)
    return 1.0 + below * YIELD_PER_LEVEL + above * YIELD_PER_LEVEL_AFTER_CAP


# Changing trades takes commitment: one switch per 5 minutes.
JOB_SWITCH_COOLDOWN = 300

# ══════════════════════════ work cooldowns ═════════════════════════════
# Mastery makes you faster: -0.6% cooldown per level, capped at -30%.

COOLDOWN_REDUCTION_PER_LEVEL = 0.006
COOLDOWN_REDUCTION_CAP = 0.30


def effective_cooldown(base_seconds: int, level: int) -> float:
    reduction = min(COOLDOWN_REDUCTION_CAP, COOLDOWN_REDUCTION_PER_LEVEL * (level - 1))
    return base_seconds * (1.0 - reduction)


# ═══════════════════════ crits, luck & bonus finds ═════════════════════

CRIT_BASE = 0.04
CRIT_PER_TOOL_TIER = 0.015
CRIT_PER_LEVEL = 0.002
CRIT_CAP = 0.25
CRIT_MULTIPLIER = 2.0  # a critical work doubles the haul


def crit_chance(level: int, tool_tier: int) -> float:
    return min(
        CRIT_CAP,
        CRIT_BASE + CRIT_PER_TOOL_TIER * tool_tier + CRIT_PER_LEVEL * (level - 1),
    )


BONUS_FIND_BASE = 0.06
BONUS_FIND_PER_LEVEL = 0.008
BONUS_FIND_CAP = 0.30
BONUS_FIND_YIELD_FACTOR = 0.5  # bonus finds are half-size hauls


def bonus_find_chance(level: int) -> float:
    return min(BONUS_FIND_CAP, BONUS_FIND_BASE + BONUS_FIND_PER_LEVEL * (level - 1))


# Rare+ drops get more likely as you level: their roll weight grows
# +2%/level, up to double the listed weight.
LUCKY_RARITIES = {"rare", "epic", "legendary"}
LUCK_PER_LEVEL = 0.02
LUCK_WEIGHT_CAP = 2.0


def effective_weight(weight: float, rarity: str, level: int) -> float:
    if rarity not in LUCKY_RARITIES:
        return weight
    return weight * min(LUCK_WEIGHT_CAP, 1.0 + LUCK_PER_LEVEL * (level - 1))


# ═══════════════════════════════ tips ══════════════════════════════════
# The coin tip earned on top of goods, scaled by skill and tool.

TIP_PER_LEVEL = 0.03
TIP_PER_TOOL_TIER = 0.05


def roll_tip(lo: int, hi: int, level: int, tool_tier: int) -> int:
    base = random.randint(lo, hi)
    scale = (1.0 + TIP_PER_LEVEL * (level - 1)) * (1.0 + TIP_PER_TOOL_TIER * tool_tier)
    return max(1, round(base * scale))


# ═══════════════════════════════ tools ═════════════════════════════════
# Yield multiplier by tool tier (tier 0 = the battered starter tool).
# Names and prices live in econ/data/tools.py; the power curve lives here.

TOOL_MULTIPLIERS = [1.0, 1.12, 1.25, 1.40, 1.60, 1.85]


def tool_multiplier(tier: int) -> float:
    tier = max(0, min(tier, len(TOOL_MULTIPLIERS) - 1))
    return TOOL_MULTIPLIERS[tier]


def total_multiplier(level: int, tool_tier: int) -> float:
    return level_yield_multiplier(level) * tool_multiplier(tool_tier)


# ═══════════════════════════ market prices ═════════════════════════════
# Deterministic per (item, UTC day) so every player sees the same market.
# Two layers: a slow 7-day sine wave (each item on its own phase, so goods
# peak on different days) plus daily seeded noise. Clamped to sane bounds.

MARKET_WAVE_AMPLITUDE = 0.10
MARKET_WAVE_PERIOD_DAYS = 7
MARKET_NOISE_LOW, MARKET_NOISE_HIGH = 0.92, 1.08
MARKET_FACTOR_MIN, MARKET_FACTOR_MAX = 0.75, 1.35


def utc_day() -> int:
    return datetime.now(timezone.utc).date().toordinal()


def _item_phase(item_key: str) -> float:
    """Stable per-item offset into the price wave (hash-randomisation safe)."""
    return (zlib.crc32(item_key.encode()) % 1000) / 1000 * MARKET_WAVE_PERIOD_DAYS


def market_factor(item_key: str, day: int | None = None) -> float:
    day = utc_day() if day is None else day
    wave = 1.0 + MARKET_WAVE_AMPLITUDE * math.sin(
        2 * math.pi * (day + _item_phase(item_key)) / MARKET_WAVE_PERIOD_DAYS
    )
    noise = random.Random(f"{day}:{item_key}").uniform(
        MARKET_NOISE_LOW, MARKET_NOISE_HIGH
    )
    return max(MARKET_FACTOR_MIN, min(MARKET_FACTOR_MAX, wave * noise))


def market_price(item_key: str, base_value: int, day: int | None = None) -> int:
    return max(1, round(base_value * market_factor(item_key, day)))


# ═══════════════════════════ daily stipend ═════════════════════════════

DAILY_BASE = 100
DAILY_STREAK_BONUS = 8
DAILY_STREAK_CAP = 30
DAILY_LEVEL_BONUS = 2
DAILY_LEVEL_BONUS_CAP = 150


def daily_payout(streak: int, total_level: int) -> tuple[int, int, int]:
    """Return (total, streak_bonus, level_bonus) for a daily claim."""
    streak_bonus = DAILY_STREAK_BONUS * min(max(streak - 1, 0), DAILY_STREAK_CAP)
    level_bonus = min(DAILY_LEVEL_BONUS_CAP, DAILY_LEVEL_BONUS * total_level)
    return DAILY_BASE + streak_bonus + level_bonus, streak_bonus, level_bonus


# ══════════════════════════ town rank titles ═══════════════════════════
# A title from total skill level across all trades. See coin_multiplier
# below for the real, mechanical payoff attached to each tier.

TOWN_RANKS = [
    (0, "🌱", "Newcomer"),
    (5, "🧺", "Apprentice"),
    (15, "🔨", "Journeyman"),
    (30, "⚒️", "Skilled Worker"),
    (50, "🏅", "Master Craftsman"),
    (80, "🏛️", "Guildmaster"),
    (120, "👑", "Town Elder"),
    (180, "🌟", "Living Legend"),
    (250, "🐉", "Legendary Sovereign"),
]


def _town_rank_index(total_level: int) -> int:
    idx = 0
    for i, (threshold, _e, _t) in enumerate(TOWN_RANKS):
        if total_level >= threshold:
            idx = i
    return idx


def town_rank(total_level: int) -> tuple[str, str]:
    """Return (emoji, title) for a player's total skill level."""
    _threshold, emoji, title = TOWN_RANKS[_town_rank_index(total_level)]
    return emoji, title


def next_town_rank(total_level: int) -> tuple[str, int] | None:
    """Return (title, levels needed) for the next rank, or None at the top."""
    for threshold, _emoji, title in TOWN_RANKS:
        if total_level < threshold:
            return title, threshold
    return None


# Town rank isn't just a title: each tier grants a small permanent
# bonus, on top of individual skill/tool bonuses, so levelling a second
# or third trade keeps paying off after your main trade is maxed out.
TOWN_RANK_BONUS_PER_TIER = 0.02  # +2% per tier, up to +16% at the top rank


def town_rank_multiplier(total_level: int) -> float:
    """The tier-only bonus shown alongside the rank badge."""
    return 1.0 + _town_rank_index(total_level) * TOWN_RANK_BONUS_PER_TIER


# Coin (tip, venture) scales with TOTAL skill level across every trade,
# continuously, not just by rank tier. A fresh player earns close to
# base rate, gold is genuinely hard to come by early; a player who has
# invested broadly across trades earns meaningfully more, up to +180%
# at total level 300, then it plateaus. Item hauls are NOT affected by
# this, only coin, so it can't be farmed by grinding a single trade.
COIN_BONUS_PER_LEVEL = 0.006
COIN_BONUS_CAP_LEVEL = 300


def coin_multiplier(total_level: int) -> float:
    continuous = 1.0 + COIN_BONUS_PER_LEVEL * min(total_level, COIN_BONUS_CAP_LEVEL)
    return town_rank_multiplier(total_level) * continuous


# ═══════════════════════════ ventures ══════════════════════════════════
# A second, job-independent way to earn: pick a path, risk it, cash in.
# Long cooldown, real choice, real risk, real reward. Town rank and the
# adventurer's own venture streak both push the payout up over time.
# Path content (names, odds, flavour) lives in econ/data/ventures.py.

VENTURE_COOLDOWN = 2 * 60 * 60  # 2 hours
VENTURE_STREAK_BONUS_PER_WIN = 0.04
VENTURE_STREAK_CAP = 10


def venture_multiplier(total_level: int, win_streak: int) -> float:
    rank_bonus = coin_multiplier(total_level)
    streak_bonus = 1.0 + VENTURE_STREAK_BONUS_PER_WIN * min(win_streak, VENTURE_STREAK_CAP)
    return rank_bonus * streak_bonus


def roll_venture(path: dict, total_level: int, win_streak: int) -> tuple[bool, int]:
    """Returns (succeeded, gold_delta). gold_delta is positive on success,
    negative (or zero) on failure."""
    mult = venture_multiplier(total_level, win_streak)
    if random.random() < path["success"]:
        return True, round(random.randint(*path["reward"]) * mult)
    loss_lo, loss_hi = path["loss"]
    loss = round(random.randint(loss_lo, loss_hi) * mult) if loss_hi else 0
    return False, -loss


# ═══════════════════════════ progress bars ═════════════════════════════

BAR_FILLED, BAR_EMPTY = "█", "░"


def progress_bar(current: int, needed: int, width: int = 12) -> str:
    filled = int(width * min(current / needed, 1.0)) if needed else width
    return BAR_FILLED * filled + BAR_EMPTY * (width - filled)
