"""Bank tier ladder: storage capacity per tier and the cost to reach it.

Tier 0 is free and every player starts there. Tiers 1+ are paid
upgrades unlocked in order, mirroring the tool tiers at the smithy.
"""

BANK_CAPACITIES = [5_000, 15_000, 40_000, 100_000, 250_000, 750_000]
BANK_UPGRADE_COSTS = [3_000, 10_000, 30_000, 75_000, 200_000]

MAX_BANK_TIER = len(BANK_CAPACITIES) - 1

assert len(BANK_UPGRADE_COSTS) == MAX_BANK_TIER


def bank_capacity(tier: int) -> int:
    tier = max(0, min(tier, MAX_BANK_TIER))
    return BANK_CAPACITIES[tier]


def bank_upgrade_cost(next_tier: int) -> int:
    """Cost to upgrade INTO `next_tier` (1..MAX_BANK_TIER)."""
    return BANK_UPGRADE_COSTS[next_tier - 1]
