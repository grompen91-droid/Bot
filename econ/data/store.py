"""The Shop's stock registry: what `.shop` can sell beyond the
trade-specific tool ladder (that's the Upgrade Tool button / `.buy`,
a confirm-gated purchase handled directly in cogs/market.py, not
stocked or rotated like everything else here).

Everything here is priced as a flat markup over an item's base value
(see STORE_CONSUMABLE_MARKUP/STORE_RARE_MARKUP below, applied in
cogs/market.py), not the daily market wave `.market`/`.sell` use --
convenience costs extra, and unlike the market it doesn't drift day to
day.

STORE_POOL is everything the shop could possibly stock: every potion
and buff food (CONSUMABLES) plus every rare-or-better RAW gathered
good (RARE_POOL, never crafted goods or consumables, never
common/uncommon). Each UTC day, STORE_ITEMS_PER_DAY (18) of those ~37
are picked at random -- deterministic and identical for every player
in every guild, changes at UTC midnight, see
formulas.store_daily_items -- and shown STORE_PAGE_SIZE (9) at a time.
So the shop's actual lineup changes daily even though the pool itself
doesn't, and it's never a guaranteed way to buy any one item.

On top of that, how MUCH of any one of today's items a player can buy
is its own separate random roll, per (player, item, UTC day) --
STORE_STOCK_RANGE_CONSUMABLE/_RARE below, see
formulas.store_daily_limit and econ/database.py's store_purchases
table for the tracking. The store is a convenience valve, not a
replacement for actually working a trade.
"""

from .consumables import CONSUMABLES
from .items import ITEMS
from .jobs import JOBS

STORE_CONSUMABLE_MARKUP = 4.0    # potions/foods: 4x their base value
STORE_RARE_MARKUP = 12.0         # rare goods: 12x, a real splurge

# Inclusive (lo, hi) range for how many of one item a player can buy
# today, rolled per (player, item, day) -- see formulas.store_daily_limit.
STORE_STOCK_RANGE_CONSUMABLE = (1, 2)
STORE_STOCK_RANGE_RARE = (1, 3)

STORE_ITEMS_PER_DAY = 18   # how many of the pool are in stock at once
STORE_PAGE_SIZE = 9        # .shop shows this many per page

_RAW_ITEM_KEYS = {item for info in JOBS.values() for item, *_rest in info["yields"]}

RARE_POOL = sorted(
    key for key, info in ITEMS.items()
    if key in _RAW_ITEM_KEYS and info["rarity"] in ("rare", "epic", "legendary")
)

STORE_POOL = sorted(set(CONSUMABLES) | set(RARE_POOL))
