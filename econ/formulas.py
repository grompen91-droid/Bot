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
DAILY_LEVEL_BONUS = 1
DAILY_LEVEL_BONUS_CAP = 660  # 100 base + 240 max streak + 660 = 1,000 max


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
PICKPOCKET_MIN_TARGET_POCKET = 50    # not worth targeting below this
PICKPOCKET_FAIL_FINE_MIN = 10
PICKPOCKET_FAIL_FINE_MAX = 30

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

SMUGGLE_GOLD_MIN, SMUGGLE_GOLD_MAX = 80, 200
SMUGGLE_FAIL_FINE_MIN, SMUGGLE_FAIL_FINE_MAX = 20, 50

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
BEG_GOLD_MIN, BEG_GOLD_MAX = 5, 20
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

MINIGAME_BASE_MIN = 50            # starter-trade floor, at skill level 1
MINIGAME_BASE_MIN_HARDEST = 400   # floor for the hardest trade to unlock
MINIGAME_MAX_MULTIPLIER = 6       # floor grows to this many times itself
MINIGAME_VARIANCE = 0.15          # +/- randomness applied on top


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
    minigame. Reward is proportional to rounds correctly cleared; a
    flawless run gets `perfect_bonus` on top. `extra_multiplier` is for
    a caller-specific bonus on top of everything else (infamy for the
    Criminal trade, fame for every other trade's minigame)."""
    if correct <= 0:
        return 0, False
    base = minigame_round_base(unlock_level, max_unlock_level, skill_level)
    variance = random.uniform(1 - MINIGAME_VARIANCE, 1 + MINIGAME_VARIANCE)
    reward = base * variance * correct * coin_multiplier(total_level) * extra_multiplier
    perfect = correct >= length > 0
    if perfect:
        reward *= perfect_bonus
    return round(reward), perfect


def minigame_length(level: int, min_len: int, max_len: int, level_per_step: int) -> int:
    """Round count for a per-job minigame attempt: starts at min_len,
    +1 round per level_per_step levels of skill, caps at max_len."""
    return min(max_len, min_len + level // level_per_step)


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

INFAMY_BONUS_PER_POINT = 0.006
INFAMY_BONUS_CAP_POINTS = 300   # +180% at the cap, matching coin_multiplier's scale

FAME_BONUS_PER_POINT = 0.006
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

CRIMINAL_WORK_MIN, CRIMINAL_WORK_MAX = 10, 24


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
# Sequence length grows with Alchemist skill level.
#
# Access: current Alchemists can always brew. Anyone else needs at
# least BREW_MIN_LEVEL_WITHOUT_JOB in the Alchemist skill (persists
# across job switches), so once you've put in the work you keep this
# even after moving on to another trade.

BREW_COOLDOWN = 6 * 60 * 60  # 6 hours
BREW_MIN_LEVEL_WITHOUT_JOB = 5
BREW_MIN_LENGTH = 3
BREW_MAX_LENGTH = 8
BREW_LEVEL_PER_STEP = 15   # +1 reagent per 15 Alchemist levels
BREW_PERFECT_BONUS = 1.5
BREW_XP_PER_SYMBOL = 3


def brew_sequence_length(level: int) -> int:
    return minigame_length(level, BREW_MIN_LENGTH, BREW_MAX_LENGTH, BREW_LEVEL_PER_STEP)


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
# regardless of their current job. Cooldown and XP reuse the same
# effective_cooldown()/roll_work_xp() every trade's .work uses; the
# real incentive is the recipes themselves (see econ/data/recipes.py),
# each priced well above its ingredients' combined market value.

CRAFTING_COOLDOWN = 90   # seconds; shorter than gathering, it's assembly


# ═══════════════════════════ progress bars ═════════════════════════════

BAR_FILLED, BAR_EMPTY = "█", "░"


def progress_bar(current: int, needed: int, width: int = 12) -> str:
    filled = int(width * min(current / needed, 1.0)) if needed else width
    return BAR_FILLED * filled + BAR_EMPTY * (width - filled)
