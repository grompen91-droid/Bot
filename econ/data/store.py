"""General Store registry: what `.store`'s General Store tab sells,
beyond the trade-specific tool ladder (that's `.shop`/`.buy`'s job
gear, kept separate and unchanged -- `.store`'s Job Store tab just
re-renders that same content, see cogs/market.py's _fill_job_store).

Everything here is priced as a flat markup over an item's base value
(see STORE_CONSUMABLE_MARKUP/STORE_RARE_MARKUP below, applied in
cogs/market.py), not the daily market wave `.market`/`.sell` use --
convenience costs extra, and unlike the market it doesn't drift day to
day.

Two sections:
- Potions & Foods: every item in CONSUMABLES, always in stock. Cheap
  work-drop items stay cheap-ish; the big crafted buffs (Feast of
  Kings, Philosopher's Masterwork, ...) become a genuine splurge,
  purely because the markup is a multiplier on their already-high
  value -- no separate tiering needed.
- Rare Goods: a small daily-rotating selection pulled only from RAW
  gathered goods (never crafted goods or consumables, and never
  common/uncommon) -- the whole point is these are otherwise a real
  grind or a rare-drop-luck away, and the rotation (same for every
  player, changes at UTC midnight, see formulas.store_rare_stock)
  means the store is never a guaranteed way to buy any one of them.

Both sections also cap how much of any one item a player can buy per
UTC day (see econ/database.py's store_purchases table for the
tracking, formulas.store_daily_limit for the roll) -- the store is a
convenience valve, not a replacement for actually working a trade, so
nobody can just buy out unlimited potions or camp a rare item. That
cap isn't a flat number either: it's randomized per (player, item,
day), so the "in stock" count next to each item varies player to
player and item to item, not just a uniform "3 of everything, always."
"""

from .items import ITEMS
from .jobs import JOBS

STORE_CONSUMABLE_MARKUP = 4.0    # potions/foods: 4x their base value
STORE_RARE_MARKUP = 12.0         # rare-stock goods: 12x, a real splurge
RARE_STOCK_SIZE = 4              # how many rare goods are in stock at once

# Inclusive (lo, hi) range for how many of one item a player can buy
# today, rolled per (player, item, day) -- see formulas.store_daily_limit.
STORE_STOCK_RANGE_CONSUMABLE = (1, 2)
STORE_STOCK_RANGE_RARE = (1, 3)

_RAW_ITEM_KEYS = {item for info in JOBS.values() for item, *_rest in info["yields"]}

RARE_POOL = sorted(
    key for key, info in ITEMS.items()
    if key in _RAW_ITEM_KEYS and info["rarity"] in ("rare", "epic", "legendary")
)
