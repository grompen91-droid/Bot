"""Bank tier ladder: storage capacity per tier and the cost to reach it.

Tier 0 is free and every player starts there. Tiers 1+ are paid
upgrades unlocked in order, mirroring the tool tiers at the smithy.
"""

# Sized against the week-to-mid-game pace: the free tier holds a
# day-one purse, the middle tiers keep up with a growing bankroll, and
# the 3M vault (500k to unlock) is a mid-game project -- by the time
# you can afford it, you've crossed the ~500k early-game boundary.
BANK_CAPACITIES = [10_000, 40_000, 120_000, 350_000, 1_000_000, 3_000_000]
BANK_UPGRADE_COSTS = [8_000, 25_000, 75_000, 200_000, 500_000]

MAX_BANK_TIER = len(BANK_CAPACITIES) - 1

assert len(BANK_UPGRADE_COSTS) == MAX_BANK_TIER


def bank_capacity(tier: int) -> int:
    tier = max(0, min(tier, MAX_BANK_TIER))
    return BANK_CAPACITIES[tier]


def bank_upgrade_cost(next_tier: int) -> int:
    """Cost to upgrade INTO `next_tier` (1..MAX_BANK_TIER)."""
    return BANK_UPGRADE_COSTS[next_tier - 1]
