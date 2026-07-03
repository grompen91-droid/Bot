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

Both sections are also capped per player per item per UTC day (see
econ/database.py's store_purchases table) -- the store is a
convenience valve, not a replacement for actually working a trade, so
nobody can just buy out unlimited potions or camp a rare item.
"""

from .items import ITEMS
from .jobs import JOBS

STORE_CONSUMABLE_MARKUP = 4.0    # potions/foods: 4x their base value
STORE_RARE_MARKUP = 12.0         # rare-stock goods: 12x, a real splurge
RARE_STOCK_SIZE = 4              # how many rare goods are in stock at once

STORE_DAILY_LIMIT_CONSUMABLE = 3  # max buys of any one potion/food per day
STORE_DAILY_LIMIT_RARE = 1        # max buys of any one rare good per day

_RAW_ITEM_KEYS = {item for info in JOBS.values() for item, *_rest in info["yields"]}

RARE_POOL = sorted(
    key for key, info in ITEMS.items()
    if key in _RAW_ITEM_KEYS and info["rarity"] in ("rare", "epic", "legendary")
)
