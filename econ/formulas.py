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
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache

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


@lru_cache(maxsize=None)
def xp_to_next(level: int) -> int:
    """XP required to advance from `level` to `level + 1`."""
    return round(XP_BASE * level**XP_EXPONENT)


def apply_xp(
    level: int, xp: int, gained: int, *, curve: Callable[[int], int] = xp_to_next,
) -> tuple[int, int, int]:
    """Return (new_level, new_xp, levels_gained) after adding XP.
    `curve` defaults to the normal trade XP curve; pass
    craft_xp_to_next for the standalone Crafting skill, which uses its
    own much gentler pace (see the crafting section below)."""
    xp += gained
    start = level
    while level < MAX_LEVEL and xp >= curve(level):
        xp -= curve(level)
        level += 1
    if level >= MAX_LEVEL:
        xp = min(xp, curve(MAX_LEVEL))
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


@lru_cache(maxsize=None)
def _item_phase(item_key: str) -> float:
    """Stable per-item offset into the price wave (hash-randomisation safe)."""
    return (zlib.crc32(item_key.encode()) % 1000) / 1000 * MARKET_WAVE_PERIOD_DAYS


# Deterministic per (item, day), so memoising is free money: inventory
# and market panels reprice dozens of items per render.
@lru_cache(maxsize=4096)
def _market_factor(item_key: str, day: int) -> float:
    wave = 1.0 + MARKET_WAVE_AMPLITUDE * math.sin(
        2 * math.pi * (day + _item_phase(item_key)) / MARKET_WAVE_PERIOD_DAYS
    )
    noise = random.Random(f"{day}:{item_key}").uniform(
        MARKET_NOISE_LOW, MARKET_NOISE_HIGH
    )
    return max(MARKET_FACTOR_MIN, min(MARKET_FACTOR_MAX, wave * noise))


def market_factor(item_key: str, day: int | None = None) -> float:
    return _market_factor(item_key, utc_day() if day is None else day)


def market_price(item_key: str, base_value: int, day: int | None = None) -> int:
    return max(1, round(base_value * market_factor(item_key, day)))


# ═══════════════════════════ the general store ═════════════════════════
# .shop's stock rotates daily, same "same for everyone, changes at UTC
# midnight" mechanism as the market's own daily seed, just picking a
# subset of a pool instead of a price factor.

@lru_cache(maxsize=64)
def _store_daily_items(pool: tuple[str, ...], size: int, day: int) -> tuple[str, ...]:
    rng = random.Random(f"store-items:{day}")
    return tuple(rng.sample(pool, min(size, len(pool))))


def store_daily_items(pool: list[str], size: int, day: int | None = None) -> list[str]:
    """Today's shop selection: deterministic and identical for every
    player in every guild, so the shop can never be relied on to
    always carry any one item -- check back tomorrow."""
    day = utc_day() if day is None else day
    return list(_store_daily_items(tuple(pool), size, day))


@lru_cache(maxsize=8192)
def store_daily_limit(
    user_id: int, item_key: str, day: int, lo: int, hi: int
) -> int:
    """How many of `item_key` THIS player can buy from .shop today --
    unlike store_daily_items (same for everyone), this is seeded per
    player too, so two players see independently random stock on the
    same item on the same day. Deterministic per (player, item, day):
    asking twice gives the same number, but it reshuffles at UTC
    midnight same as everything else in the store."""
    rng = random.Random(f"store-limit:{user_id}:{item_key}:{day}")
    return rng.randint(lo, hi)


# ═══════════════════════════ daily stipend ═════════════════════════════
# Sized against the week-to-mid-game pace (~500k gold in ~7 active
# days): logging in every day should fund a meaningful slice of that,
# not pocket change next to one minigame run.

DAILY_BASE = 1_000
DAILY_STREAK_BONUS = 40
DAILY_STREAK_CAP = 30
DAILY_LEVEL_BONUS = 5
DAILY_LEVEL_BONUS_CAP = 7_800  # 1,000 base + 1,200 max streak + 7,800 = 10,000 max


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


# ═══════════════════════════ pickpocketing ═════════════════════════════
# Steal from another player's POCKET only, never their bank. That's the
# whole point of the bank: a real, meaningful way to protect your gold.
# Gated behind the Criminal trade (see PICKPOCKET_MIN_LEVEL_WITHOUT_JOB
# below): both odds and steal size scale with Criminal skill level,
# so investing in the trade pays off here too, not just at .work.

PICKPOCKET_MIN_LEVEL_WITHOUT_JOB = 5   # same access rule as .brew

PICKPOCKET_SUCCESS_BASE = 0.25
PICKPOCKET_SUCCESS_PER_LEVEL = 0.003
PICKPOCKET_SUCCESS_CAP = 0.55

PICKPOCKET_STEAL_MIN = 0.25          # floor, of the target's pocket gold
PICKPOCKET_STEAL_MAX_BASE = 0.50     # ceiling at skill level 1
PICKPOCKET_STEAL_MAX_PER_LEVEL = 0.0025
PICKPOCKET_STEAL_MAX_CAP = 0.75      # ceiling at high skill

PICKPOCKET_COOLDOWN = 20 * 60        # 20 minutes between attempts
PICKPOCKET_VICTIM_SHIELD = 10 * 60   # victim is safe for 10 minutes after
PICKPOCKET_MIN_TARGET_POCKET = 250   # not worth targeting below this
PICKPOCKET_FAIL_FINE_MIN = 60
PICKPOCKET_FAIL_FINE_MAX = 150

PICKPOCKET_INFAMY_MIN = 1            # every attempt builds a little
PICKPOCKET_INFAMY_MAX = 3            # notoriety, win or lose


def pickpocket_success_chance(skill_level: int) -> float:
    return min(
        PICKPOCKET_SUCCESS_CAP,
        PICKPOCKET_SUCCESS_BASE + PICKPOCKET_SUCCESS_PER_LEVEL * max(0, skill_level - 1),
    )


def pickpocket_steal_max(skill_level: int) -> float:
    return min(
        PICKPOCKET_STEAL_MAX_CAP,
        PICKPOCKET_STEAL_MAX_BASE + PICKPOCKET_STEAL_MAX_PER_LEVEL * max(0, skill_level - 1),
    )


def roll_pickpocket(target_pocket: int, skill_level: int) -> tuple[bool, int]:
    """Returns (success, gold_delta): positive gold stolen on success,
    negative (a fine the attacker pays) on failure. Odds and steal size
    both scale with the attacker's Criminal skill level."""
    if random.random() < pickpocket_success_chance(skill_level):
        pct = random.uniform(PICKPOCKET_STEAL_MIN, pickpocket_steal_max(skill_level))
        return True, max(1, round(target_pocket * pct))
    fine = random.randint(PICKPOCKET_FAIL_FINE_MIN, PICKPOCKET_FAIL_FINE_MAX)
    return False, -fine


# ═══════════════════════════ smuggling ═══════════════════════════════════
# Sits between .pickpocket (petty, frequent, small) and .rob (huge,
# rare, one mistake wipes your reputation): a solo, no-target crime
# with a real chance of losing the goods, but never the full-wipe risk
# .rob carries. Same access rule and skill scaling as pickpocketing.

SMUGGLE_MIN_LEVEL_WITHOUT_JOB = 5   # same access rule as .brew
SMUGGLE_COOLDOWN = 60 * 60          # 1 hour between runs

SMUGGLE_SUCCESS_BASE = 0.45
SMUGGLE_SUCCESS_PER_LEVEL = 0.003
SMUGGLE_SUCCESS_CAP = 0.75

SMUGGLE_GOLD_MIN, SMUGGLE_GOLD_MAX = 700, 1_800
SMUGGLE_FAIL_FINE_MIN, SMUGGLE_FAIL_FINE_MAX = 150, 400

SMUGGLE_INFAMY_MIN = 4   # a real haul, but still less notoriety than a
SMUGGLE_INFAMY_MAX = 8   # successful bank job (see ROB_SUCCESS_INFAMY_*)


def smuggle_success_chance(skill_level: int) -> float:
    return min(
        SMUGGLE_SUCCESS_CAP,
        SMUGGLE_SUCCESS_BASE + SMUGGLE_SUCCESS_PER_LEVEL * max(0, skill_level - 1),
    )


def roll_smuggle(skill_level: int, infamy: int, total_level: int) -> tuple[bool, int]:
    """Returns (success, gold_delta): positive gold smuggled through on
    success, negative (goods confiscated, plus a fine) on failure."""
    if random.random() < smuggle_success_chance(skill_level):
        base = random.randint(SMUGGLE_GOLD_MIN, SMUGGLE_GOLD_MAX)
        level_scale = 1.0 + TIP_PER_LEVEL * (skill_level - 1)
        gold = round(base * level_scale * infamy_multiplier(infamy) * coin_multiplier(total_level))
        return True, gold
    fine = random.randint(SMUGGLE_FAIL_FINE_MIN, SMUGGLE_FAIL_FINE_MAX)
    return False, -fine


# ═══════════════════════════════ begging ═════════════════════════════════
# The one command that needs nothing at all: no job, no skill, no
# unlock. A tiny, reliable trickle of gold with a short cooldown, so
# there's always *something* to do between other cooldowns. Costs a
# little fame if you have any (a proud townsfolk begging is a small
# public embarrassment), but never pushes you into infamy -- it stops
# at neutral (0) if you're already there or already infamous.

BEG_COOLDOWN = 8 * 60   # 8 minutes
BEG_GOLD_MIN, BEG_GOLD_MAX = 25, 100
BEG_REPUTATION_LOSS_MIN, BEG_REPUTATION_LOSS_MAX = 1, 3


def roll_beg(reputation: int) -> tuple[int, int]:
    """Returns (gold, reputation_delta). reputation_delta is 0 unless
    you currently have fame (reputation > 0), in which case it's a
    small negative nudge floored so it can never cross into infamy."""
    gold = random.randint(BEG_GOLD_MIN, BEG_GOLD_MAX)
    if reputation > 0:
        loss = random.randint(BEG_REPUTATION_LOSS_MIN, BEG_REPUTATION_LOSS_MAX)
        return gold, -min(loss, reputation)
    return gold, 0


# ═══════════════════════════ job minigames ══════════════════════════════
# Shared reward curve for every per-job minigame (the cauldron brew,
# and its siblings for the other trades). Each round has a base value
# that:
#   1. Starts low for a starter trade, higher for a trade that was
#      harder to unlock in the first place (Alchemist pays much more
#      per round than Farmer from square one).
#   2. Grows as YOUR skill in that specific trade grows: level 1 pays
#      the tier's floor, level MAX_LEVEL pays MINIGAME_MAX_MULTIPLIER
#      times that floor.
# On top of that, coin_multiplier(total_level) still applies (total
# skill across every trade), and a flawless run gets a perfect bonus.
# This is what every per-job minigame's roll_*_reward() should build on.

MINIGAME_BASE_MIN = 80            # starter-trade floor, at skill level 1
MINIGAME_BASE_MIN_HARDEST = 400   # floor for the hardest trade to unlock
MINIGAME_MAX_MULTIPLIER = 6       # floor grows to this many times itself
MINIGAME_VARIANCE = 0.15          # +/- randomness applied on top

# A run pays as if it were this many rounds, scaled by the FRACTION of
# rounds actually cleared -- NOT by the raw round count. Session length
# varies per job and difficulty (3 to 10+ rounds), and paying per round
# let the longest games compound with reward_mult and the perfect
# bonus into most of the whole economy's income. Difficulty pays
# through reward_mult; length pays through XP (which stays per-round).
MINIGAME_PAID_ROUNDS = 4


def minigame_round_base(unlock_level: int, max_unlock_level: int, skill_level: int) -> float:
    """Per-round reward before variance, coin_multiplier, and any
    perfect bonus. `unlock_level` is this trade's own unlock threshold,
    `max_unlock_level` the hardest trade's, so the floor interpolates
    between MINIGAME_BASE_MIN and MINIGAME_BASE_MIN_HARDEST."""
    tier_frac = (unlock_level / max_unlock_level) if max_unlock_level else 0.0
    floor = MINIGAME_BASE_MIN + (MINIGAME_BASE_MIN_HARDEST - MINIGAME_BASE_MIN) * tier_frac
    level_frac = (max(1, skill_level) - 1) / (MAX_LEVEL - 1)
    return floor * (1 + (MINIGAME_MAX_MULTIPLIER - 1) * level_frac)


def roll_minigame_reward(
    correct: int, length: int, unlock_level: int, max_unlock_level: int,
    skill_level: int, total_level: int, *,
    perfect_bonus: float = 1.5, extra_multiplier: float = 1.0,
) -> tuple[int, bool]:
    """Returns (gold, was_perfect) for one attempt at a per-job
    minigame. Reward is proportional to the FRACTION of rounds cleared
    (see MINIGAME_PAID_ROUNDS); a flawless run gets `perfect_bonus` on
    top. `extra_multiplier` is for a caller-specific bonus on top of
    everything else (infamy for the Criminal trade, fame for every
    other trade's minigame, and the difficulty tier's reward_mult)."""
    if correct <= 0 or length <= 0:
        return 0, False
    base = minigame_round_base(unlock_level, max_unlock_level, skill_level)
    variance = random.uniform(1 - MINIGAME_VARIANCE, 1 + MINIGAME_VARIANCE)
    completion = min(1.0, correct / length)
    reward = (
        base * variance * MINIGAME_PAID_ROUNDS * completion
        * coin_multiplier(total_level) * extra_multiplier
    )
    perfect = correct >= length
    if perfect:
        reward *= perfect_bonus
    return round(reward), perfect


# ═══════════════════ minigame difficulty tiers ══════════════════════════
# Every per-job minigame (and the cauldron brew) is picked, not auto-
# scaled: running the command shows an Easy/Medium/Hard picker. Easy is
# always open; Medium and Hard unlock at DIFFICULTY_UNLOCK_LEVEL in that
# specific trade's skill, so a higher skill level buys access to a
# harder, longer, better-paying version of the SAME minigame, on top of
# minigame_round_base's existing per-round scaling by skill level.
#
# length_frac interpolates between a config's own min_len and max_len
# (already tuned per job), so Easy always equals min_len and Hard
# always equals max_len with zero extra per-job data needed. bonus is a
# generic "how many extra units of raw challenge" knob each session
# kind spends on whatever fits it (MatchSession: extra decoys,
# SpotDiffSession: extra grid tiles). timeout_mult tightens whichever
# timer that kind uses (round_timeout, step_timeout, reel_window, the
# brew's reveal/answer timing). reward_mult is a straight multiplier
# folded into roll_minigame_reward's extra_multiplier.

DIFFICULTIES = {
    "easy": {
        "label": "Easy", "emoji": "🟢", "unlock_level": 1,
        "length_frac": 0.0, "bonus": 0, "timeout_mult": 1.00, "reward_mult": 1.0,
    },
    "medium": {
        "label": "Medium", "emoji": "🟡", "unlock_level": 5,
        "length_frac": 0.5, "bonus": 1, "timeout_mult": 0.80, "reward_mult": 1.35,
    },
    "hard": {
        "label": "Hard", "emoji": "🔴", "unlock_level": 10,
        "length_frac": 1.0, "bonus": 2, "timeout_mult": 0.62, "reward_mult": 1.85,
    },
}
DIFFICULTY_ORDER = ("easy", "medium", "hard")


def difficulty_length(min_len: int, max_len: int, difficulty: str) -> int:
    """Round count for a chosen difficulty tier: Easy = min_len exactly,
    Hard = max_len exactly, Medium interpolates between them."""
    frac = DIFFICULTIES[difficulty]["length_frac"]
    return round(min_len + (max_len - min_len) * frac)


def difficulty_unlocked(skill_level: int, difficulty: str) -> bool:
    return skill_level >= DIFFICULTIES[difficulty]["unlock_level"]


MINIGAME_XP_PER_ROUND = 3
MINIGAME_PERFECT_BONUS = 1.5
MINIGAME_MIN_LEVEL_WITHOUT_JOB = 5   # same access rule as .brew

# Cooldown interpolates the same way the reward floor does: a starter
# trade's minigame can be replayed often for a small payout, a
# late-game trade's pays much more but far less often. Alchemist's
# .brew sits just above this range at a flat 6h (see BREW_COOLDOWN).
MINIGAME_COOLDOWN_MIN = 45 * 60        # starter trades, 45 minutes
MINIGAME_COOLDOWN_MAX = 5 * 60 * 60    # hardest non-Alchemist trade, 5 hours


def minigame_cooldown(unlock_level: int, max_unlock_level: int) -> int:
    frac = (unlock_level / max_unlock_level) if max_unlock_level else 0.0
    return round(MINIGAME_COOLDOWN_MIN + (MINIGAME_COOLDOWN_MAX - MINIGAME_COOLDOWN_MIN) * frac)


# ═══════════════════════════ infamy & fame ══════════════════════════════
# One signed reputation counter, not two: crime (Criminal .work,
# .pickpocket, the .rob bank job) pulls it down, succeeding at any of
# the OTHER, legitimate minigames (.harvest, .dig, .fish, .fell,
# .hunt, .bake, .tend, .brew) pulls it up. "Infamy" and "fame" are just
# the two directions of the same number: infamy is how far negative it
# is, fame how far positive. A bank job gone wrong (getting caught in
# .rob) snaps it straight back to 0 -- the one real risk in the whole
# system, and it costs whichever direction you'd built up.

INFAMY_BONUS_PER_POINT = 0.003
INFAMY_BONUS_CAP_POINTS = 300   # +90% at the cap

FAME_BONUS_PER_POINT = 0.003
FAME_BONUS_CAP_POINTS = 300


def reputation_infamy(reputation: int) -> int:
    """How infamous: the magnitude of reputation below 0."""
    return max(0, -reputation)


def reputation_fame(reputation: int) -> int:
    """How famous: the magnitude of reputation above 0."""
    return max(0, reputation)


def infamy_multiplier(infamy: int) -> float:
    return 1.0 + INFAMY_BONUS_PER_POINT * min(max(infamy, 0), INFAMY_BONUS_CAP_POINTS)


def fame_multiplier(fame: int) -> float:
    return 1.0 + FAME_BONUS_PER_POINT * min(max(fame, 0), FAME_BONUS_CAP_POINTS)


MINIGAME_FAME_ON_SUCCESS = 1   # flat reputation gain per successful legit minigame clear

CRIMINAL_WORK_INFAMY_MIN = 2   # infamy earned per Criminal .work, win or lose
CRIMINAL_WORK_INFAMY_MAX = 5

ROB_SUCCESS_INFAMY_MIN = 8     # a successful bank job is worth much more
ROB_SUCCESS_INFAMY_MAX = 20    # notoriety than an honest day's crime


# ═══════════════════════════ the criminal trade ═════════════════════════
# Criminal is free from the start, like Farmer/Miner/Fisherman, but
# pays in gold alone -- no goods to sell. Payout scales with skill
# level (like a tip), tools (lockpicks etc, same shop/buy flow as
# every other trade), infamy (the whole point of playing dirty), and
# total skill level across every trade, same as everyone else.

CRIMINAL_WORK_MIN, CRIMINAL_WORK_MAX = 90, 220


def roll_criminal_work(level: int, tool_tier: int, infamy: int, total_level: int) -> int:
    base = random.randint(CRIMINAL_WORK_MIN, CRIMINAL_WORK_MAX)
    level_scale = 1.0 + TIP_PER_LEVEL * (level - 1)
    reward = (
        base * level_scale * tool_multiplier(tool_tier)
        * infamy_multiplier(infamy) * coin_multiplier(total_level)
    )
    return max(1, round(reward))


# ═══════════════════════════ the cauldron brew ═════════════════════════
# A memory minigame: recall a reagent sequence in order. No risk of
# loss, reward scales with how many you get right, with a bonus for a
# flawless brew. A long cooldown and a bigger per-attempt payout than
# .venture make it worth doing once a day's business is settled.
# Sequence length is picked via the same Easy/Medium/Hard difficulty
# tiers as every other per-job minigame (see DIFFICULTIES above).
#
# Access: current Alchemists can always brew. Anyone else needs at
# least BREW_MIN_LEVEL_WITHOUT_JOB in the Alchemist skill (persists
# across job switches), so once you've put in the work you keep this
# even after moving on to another trade.

BREW_COOLDOWN = 6 * 60 * 60  # 6 hours
BREW_MIN_LEVEL_WITHOUT_JOB = 5
BREW_MIN_LENGTH = 3
BREW_MAX_LENGTH = 8
BREW_PERFECT_BONUS = 1.5
BREW_XP_PER_SYMBOL = 3


def brew_sequence_length(difficulty: str) -> int:
    return difficulty_length(BREW_MIN_LENGTH, BREW_MAX_LENGTH, difficulty)


def roll_brew_reward(
    correct: int, length: int, skill_level: int, total_level: int,
    unlock_level: int, max_unlock_level: int, *, extra_multiplier: float = 1.0,
) -> tuple[int, bool]:
    """Returns (gold, was_perfect). Reward is proportional to reagents
    correctly recalled; a flawless brew gets a 50% bonus on top."""
    return roll_minigame_reward(
        correct, length, unlock_level, max_unlock_level, skill_level,
        total_level, perfect_bonus=BREW_PERFECT_BONUS, extra_multiplier=extra_multiplier,
    )


# ═══════════════════════════════ crafting ═══════════════════════════════
# A standalone skill, not tied to any trade -- anyone can craft
# regardless of their current job. Cooldown and XP-per-craft reuse the
# same effective_cooldown()/roll_work_xp() every trade's .work uses.
# The LEVEL CURVE is the same shape as the shared xp_to_next() (a
# polynomial), but tuned steeper on both ends: recipes unlock early
# (level 1/2/3/4/5, see econ/data/recipes.py) so the payoff arrives
# fast, but the climb afterward outpaces even a trade's own curve --
# by design, crafting is the hardest skill in the game to keep
# levelling once you're a few levels in.

CRAFT_XP_BASE = 90
CRAFT_XP_EXPONENT = 1.65


@lru_cache(maxsize=None)
def craft_xp_to_next(level: int) -> int:
    """XP required to advance Crafting from `level` to `level + 1`."""
    return round(CRAFT_XP_BASE * level**CRAFT_XP_EXPONENT)


CRAFTING_COOLDOWN = 90   # seconds; shorter than gathering, it's assembly


# ══════════════════════════════ the town ═══════════════════════════════
# The mid-game settlement layer: found a personal town for a flat 500k
# gold (TOWN_HALL_FOUNDING_COST -> hall level 1), then grow it with
# gold + construction materials (econ/data/materials.py). Buildings and
# workers live in econ/data/town_buildings.py / town_workers.py; this
# section is the shared cost curve and bonus-stacking math both of
# those data files and cogs/town.py build on. Reading active building/
# worker tiers out of the database and combining them with the data
# registries is econ/town.py's job (kept separate from here for the
# same reason buffs.py is: this file stays pure, no DB, no data-module
# imports).
#
# Sized against actually-simulated income, not a guess: Town Hall's own
# ladder plus every building/worker tier totals roughly 2.8M gold on
# top of the 500k founding cost -- about two weeks for a hardcore
# grinder, a bit over a month of genuinely dedicated play, a few
# months at a casual pace, plus a proportionate pile of materials.

TOWN_HALL_FOUNDING_COST = 500_000  # the one-time buy that creates hall level 1
TOWN_HALL_MAX_LEVEL = 9

# Level 2..9 cost curve: gold grows ~x1.3/level, so level 9 costs
# roughly 6x level 2.
TOWN_HALL_BASE_GOLD = 18_000
TOWN_HALL_GOLD_GROWTH = 1.3
TOWN_HALL_BASE_MATERIAL_QTY = 30
TOWN_HALL_MATERIAL_QTY_GROWTH = 1.35


def town_hall_upgrade_cost(next_level: int) -> tuple[int, int]:
    """Cost to upgrade INTO `next_level` (2..TOWN_HALL_MAX_LEVEL): (gold,
    material_qty) -- cogs/town.py picks the actual material from the
    "universal" group at a rarity matching the level."""
    n = next_level - 2  # 0-indexed past the free founding level
    gold = round(TOWN_HALL_BASE_GOLD * TOWN_HALL_GOLD_GROWTH ** n)
    qty = round(TOWN_HALL_BASE_MATERIAL_QTY * TOWN_HALL_MATERIAL_QTY_GROWTH ** n)
    return gold, qty


# Building/worker tiers reuse this one exponential generator instead of
# 180 hand-tuned tuples: each building/worker only needs a base gold
# cost and a base material quantity. Tier 1..5 maps onto its material
# group's five rarities in order (common -> legendary, see
# econ/data/materials.py's MATERIAL_GROUPS), so later tiers don't just
# cost "more of the same," they demand rarer stock too.

BUILDING_GOLD_GROWTH = 1.6
BUILDING_MATERIAL_QTY_GROWTH = 1.4
WORKER_GOLD_GROWTH = 1.5
WORKER_MATERIAL_QTY_GROWTH = 1.3


def tier_cost(
    base_gold: int, base_qty: int, tier: int, *,
    gold_growth: float, qty_growth: float,
) -> tuple[int, int]:
    """(gold, material_qty) for `tier` (1-indexed). Shared by
    building_tier_cost/worker_tier_cost below -- the only difference
    between a building and a worker ladder is which growth constants
    they use."""
    n = tier - 1
    gold = round(base_gold * gold_growth ** n)
    qty = round(base_qty * qty_growth ** n)
    return gold, qty


def building_tier_cost(base_gold: int, base_qty: int, tier: int) -> tuple[int, int]:
    return tier_cost(
        base_gold, base_qty, tier,
        gold_growth=BUILDING_GOLD_GROWTH, qty_growth=BUILDING_MATERIAL_QTY_GROWTH,
    )


def worker_tier_cost(base_gold: int, base_qty: int, tier: int) -> tuple[int, int]:
    return tier_cost(
        base_gold, base_qty, tier,
        gold_growth=WORKER_GOLD_GROWTH, qty_growth=WORKER_MATERIAL_QTY_GROWTH,
    )


# ── production buildings: passive, offline-accruing output ─────────────
# Each production building's per-hour output rate grows with its own
# tier and any worker assigned to it; storage caps grow with tier too,
# same shape as the bank's capacity ladder, so there's always a reason
# to both upgrade AND come back and collect.

BUILDING_RATE_GROWTH = 1.6          # output/hour multiplier per building tier
WORKER_RATE_BONUS_PER_TIER = 0.25   # +25% of the building's rate per worker tier
WORKER_RATE_BONUS_CAP = 1.0         # workers can't more than double a building's rate (+100% max),
                                     # however many are hired onto it or however high their tiers
BUILDING_CAP_GROWTH = 1.8           # storage cap multiplier per building tier
STOREHOUSE_CAP_BONUS_PER_TIER = 0.35  # +35% cap per Storehouse tier, every building at once
MAX_OFFLINE_HOURS = 48              # production stops accruing past this long uncollected


def building_output_rate(base_rate_per_hour: float, building_tier: int, worker_tier: int) -> float:
    """Units/hour a built production building generates, tier 1..5, with
    an optional linked worker (tier 0..5) boosting it further -- two
    workers can be linked to one building (see workers_for_building),
    so `worker_tier` is their SUMMED tiers and can reach 10; the boost
    itself is capped at WORKER_RATE_BONUS_CAP regardless."""
    if building_tier <= 0:
        return 0.0
    tier_mult = BUILDING_RATE_GROWTH ** (building_tier - 1)
    worker_mult = 1.0 + min(WORKER_RATE_BONUS_CAP, WORKER_RATE_BONUS_PER_TIER * worker_tier)
    return base_rate_per_hour * tier_mult * worker_mult


def building_storage_cap(base_cap: float, building_tier: int, storehouse_tier: int = 0) -> float:
    """Max units a building can bank before collection stops adding
    more. `storehouse_tier` is the Storehouse utility building's own
    tier, which raises every production building's cap at once."""
    if building_tier <= 0:
        return 0.0
    tier_mult = BUILDING_CAP_GROWTH ** (building_tier - 1)
    storehouse_mult = 1.0 + STOREHOUSE_CAP_BONUS_PER_TIER * storehouse_tier
    return base_cap * tier_mult * storehouse_mult


def building_collect(
    base_rate_per_hour: float, base_cap: float, building_tier: int, worker_tier: int,
    storehouse_tier: int, elapsed_seconds: float,
) -> int:
    """Whole units accrued since last collected, capped by both the
    offline-hours ceiling and the building's own storage cap."""
    if building_tier <= 0:
        return 0
    hours = min(elapsed_seconds / 3600.0, MAX_OFFLINE_HOURS)
    rate = building_output_rate(base_rate_per_hour, building_tier, worker_tier)
    cap = building_storage_cap(base_cap, building_tier, storehouse_tier)
    return int(min(hours * rate, cap))


# ── worker hiring capacity ──────────────────────────────────────────────
# The Workers' Lodge utility building gates .workers entirely (tier 0 =
# not built = no hiring at all) and its tier caps how many workers can
# be hired at once, so building it is a real prerequisite, not a
# formality.

LODGE_BASE_SLOTS = 4
LODGE_SLOTS_PER_TIER = 4


def worker_slots(lodge_tier: int) -> int:
    return 0 if lodge_tier <= 0 else LODGE_BASE_SLOTS + LODGE_SLOTS_PER_TIER * (lodge_tier - 1)


# ── permanent bonus buildings ────────────────────────────────────────────
# Guild Hall/Great Library/Town Square/Tavern/Temple/Watchtower each add
# a percentage into ONE of these effects (see each building's "effect"
# key in econ/data/town_buildings.py), plus its linked town-wide worker
# if hired. Kept separate from buffs.py's temporary-potion caps
# (MAX_GOLD_BONUS etc.) -- this is permanent progression like a rank-up
# or a tool tier, not a consumable, and stacks alongside coin_multiplier
# at the exact same call sites in cogs/jobs.py -- but every effect still
# has its OWN ceiling below, so fully maxing a building and its worker
# can't spiral unbounded.
#
# The percentage is deliberately back-loaded across the 5 tiers rather
# than flat: each tier's SHARE of the eventual tier-5 total grows
# ~x1.8 tier over tier, so tier 1 gives barely a taste (~5% of the
# total) and tier 5 alone delivers almost half of it. Paired with
# BONUS_BUILDING_GOLD_GROWTH/BONUS_WORKER_GOLD_GROWTH below (steeper
# than the standard building/worker cost curve), the big power spike
# and the big price tag land on the same late tiers -- reaching it is
# meant to be a late-month push, not a first-week side project.

_TIER_BACKLOAD_RATIO = 1.8
_TIER_BACKLOAD_WEIGHTS = [_TIER_BACKLOAD_RATIO**i for i in range(5)]
_TIER_BACKLOAD_TOTAL = sum(_TIER_BACKLOAD_WEIGHTS)
TIER_BACKLOAD_SHARE = [w / _TIER_BACKLOAD_TOTAL for w in _TIER_BACKLOAD_WEIGHTS]  # ~[5%, 8%, 15%, 27%, 45%]

# Total percentage each bonus building grants once fully maxed (tier 5)
# -- unchanged from the old flat-per-tier totals, only the SHAPE of the
# climb to get there changed.
BONUS_BUILDING_MAX_PCT = {
    "gold": 0.25,      # Guild Hall: up to +25% gold at tier 5
    "xp": 0.25,        # Great Library: up to +25% XP at tier 5
    "cooldown": 0.15,  # Town Square: up to -15% cooldown at tier 5
    "crit": 0.10,      # Tavern: up to +10% crit chance at tier 5
    "luck": 0.15,      # Temple: up to +15% bonus-find chance at tier 5
    "defense": 0.30,   # Watchtower: up to +30% crime defense/luck at tier 5
}
TOWNWIDE_WORKER_MAX_PCT = 0.75  # every town-wide worker adds up to +75% to its linked effect at tier 5

# Steeper than BUILDING_GOLD_GROWTH/WORKER_GOLD_GROWTH -- tier 1 costs
# exactly the same as it would on the standard curve (growth^0 = 1
# either way), so dipping a toe in stays cheap, but tiers 4-5 (where
# the backloaded % actually lives) cost noticeably more than a regular
# building/worker's would.
BONUS_BUILDING_GOLD_GROWTH = 2.0
BONUS_WORKER_GOLD_GROWTH = 1.9


def bonus_building_pct(effect: str, tier: int) -> float:
    """Cumulative % a bonus building grants at `tier` (0..5)."""
    if tier <= 0:
        return 0.0
    return BONUS_BUILDING_MAX_PCT[effect] * sum(TIER_BACKLOAD_SHARE[:tier])


def townwide_worker_pct(tier: int) -> float:
    """Cumulative % a town-wide worker adds to its linked effect at
    `tier` (0..5), same back-loaded shape as bonus_building_pct."""
    if tier <= 0:
        return 0.0
    return TOWNWIDE_WORKER_MAX_PCT * sum(TIER_BACKLOAD_SHARE[:tier])

# Ceilings on the totals above -- sized so maxing BOTH a bonus building
# (tier 5) and its linked town-wide worker (tier 5) lands almost
# exactly on the cap (0.05*5 + 0.15*5 = 1.00), the same "your best
# possible build just reaches the ceiling" tuning as CRIT_CAP/
# BONUS_FIND_CAP above.
TOWN_GOLD_CAP = 1.0      # town bonuses alone can't more than double gold income
TOWN_XP_CAP = 1.0        # ...or more than double XP gain
TOWN_COOLDOWN_CAP = 0.6  # town bonuses alone can't cut cooldown by more than 60%


def apply_town_gold(base: float, totals: dict[str, float]) -> float:
    return base * (1.0 + min(TOWN_GOLD_CAP, totals.get("gold", 0.0)))


def apply_town_xp(base: float, totals: dict[str, float]) -> float:
    return base * (1.0 + min(TOWN_XP_CAP, totals.get("xp", 0.0)))


def apply_town_cooldown(base: float, totals: dict[str, float]) -> float:
    return base * (1.0 - min(TOWN_COOLDOWN_CAP, totals.get("cooldown", 0.0)))


def apply_town_crit(base_chance: float, totals: dict[str, float]) -> float:
    return min(0.9, base_chance + totals.get("crit", 0.0))


def apply_town_luck(base_chance: float, totals: dict[str, float]) -> float:
    return min(0.9, base_chance + totals.get("luck", 0.0))


# ── .study and .patrol: the two commands a specific building unlocks ────
# (see cogs/town.py). Cooldowns are tracked in the shared
# minigame_cooldowns table under fake "job" keys ("study"/"patrol"),
# same trick already used for .beg/.smuggle/.rob there.

STUDY_COOLDOWN = 4 * 60 * 60
STUDY_GOLD_COST = 20_000
STUDY_XP_PER_LIBRARY_TIER = 400
PATROL_COOLDOWN = 6 * 60 * 60

# ── .gather: the active, hands-on way to get materials ──────────────────
# .supply only stocks common/uncommon materials now (see
# MATERIAL_SUPPLY_MAX_RARITY in econ/data/materials.py) -- rare and
# above have to be earned: either a production building's own passive
# trickle once it's already at that tier, or .gather, a short-cooldown
# active command per built production building. Each run yields a
# batch of that building's CURRENT tier material, scaled by the
# building's tier and how broadly you've levelled (total_level), plus a
# small chance at ONE unit of the NEXT tier's material -- the bridge
# that lets a building actually reach its next tier instead of being
# stuck waiting on a material nothing yet produces.

GATHER_COOLDOWN = 45 * 60  # 45 minutes -- meant to be run several times a day
GATHER_BASE_YIELD = 4
GATHER_YIELD_PER_BUILDING_TIER = 3
GATHER_YIELD_PER_TOTAL_LEVEL = 0.05
GATHER_YIELD_LEVEL_CAP = 150
GATHER_NEXT_TIER_CHANCE = 0.20


def gather_yield(building_tier: int, total_level: int) -> int:
    level_bonus = 1.0 + GATHER_YIELD_PER_TOTAL_LEVEL * min(total_level, GATHER_YIELD_LEVEL_CAP)
    return max(1, round((GATHER_BASE_YIELD + GATHER_YIELD_PER_BUILDING_TIER * building_tier) * level_bonus))


def roll_gather_bridge() -> bool:
    """Whether this gather also turns up one unit of the NEXT tier's
    material -- unlocked at a flat rate, not scaled by level, so it
    stays a genuine "and sometimes you get lucky" moment."""
    return random.random() < GATHER_NEXT_TIER_CHANCE


# A small, job-agnostic chance for ANY trade's `.work` to also turn up
# a "universal" group material (Nails, Blueprint Scroll, Enchanted
# Dust, ...) -- the town-wide materials (Town Hall's own ladder, the
# utility/bonus buildings) aren't tied to any one production building,
# so this is their only earn-it-by-working path once .supply stops
# selling their rare+ tiers. Rarity leans in your favour the more total
# skill you've built, same shape as effective_weight's rare-item luck.
WORK_DROP_MATERIAL_CHANCE = 0.05
WORK_DROP_MATERIAL_QTY = (1, 3)
WORK_DROP_MATERIAL_LEVEL_CAP = 150


def roll_universal_material_rarity(total_level: int) -> str:
    """Which rarity tier of the universal group a work-drop lands on --
    weighted toward "rare" early, shifting toward "epic"/"legendary"
    the more total skill you've built."""
    factor = min(total_level, WORK_DROP_MATERIAL_LEVEL_CAP) / WORK_DROP_MATERIAL_LEVEL_CAP
    weights = {
        "rare": 0.75 - 0.35 * factor,
        "epic": 0.20 + 0.20 * factor,
        "legendary": 0.05 + 0.15 * factor,
    }
    rarities = list(weights.keys())
    return random.choices(rarities, weights=list(weights.values()), k=1)[0]


# ═══════════════════════════ progress bars ═════════════════════════════

BAR_FILLED, BAR_EMPTY = "█", "░"


def progress_bar(current: int, needed: int, width: int = 12) -> str:
    filled = int(width * min(current / needed, 1.0)) if needed else width
    return BAR_FILLED * filled + BAR_EMPTY * (width - filled)
