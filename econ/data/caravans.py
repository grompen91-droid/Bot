"""Caravan route registry for `.caravan`: send your town's surplus out on
a trade route that takes real time to complete, then come back later and
collect however it went. See econ/formulas.py's ".caravan" section for
the duration/reward/outcome math, cogs/town.py for the UI.

Routes are gated by POPULATION (formulas.town_population), not hall
level or a building tier -- a caravan is about how much town you can
spare, not what you've specifically built. Only one caravan can be out
at a time (town_caravans is keyed on (guild_id, user_id), not a history
table), so this stays a periodic check-in, not something to spam.
"""

CARAVAN_ROUTES: dict[str, dict] = {
    "local_run": dict(
        key="local_run", name="Local Trade Run", emoji="🛒",
        min_population=0, duration_hours=2,
        send_gold_cost=800, base_gold_reward=2_400, reward_rarity="common",
        flavor="A short hop to the neighbouring market and back before supper.",
    ),
    "merchant_caravan": dict(
        key="merchant_caravan", name="Merchant Caravan", emoji="🐎",
        min_population=150, duration_hours=8,
        send_gold_cost=4_500, base_gold_reward=13_000, reward_rarity="uncommon",
        flavor="A proper wagon train, guards and all, bound for the trade road.",
    ),
    "grand_expedition": dict(
        key="grand_expedition", name="Grand Expedition", emoji="🐫",
        min_population=400, duration_hours=20,
        send_gold_cost=15_000, base_gold_reward=44_000, reward_rarity="rare",
        flavor="Weeks of provisioning, spent on a run to the far markets.",
    ),
    "legendary_venture": dict(
        key="legendary_venture", name="Legendary Venture", emoji="👑",
        min_population=700, duration_hours=40,
        send_gold_cost=42_000, base_gold_reward=135_000, reward_rarity="epic",
        flavor="The whole town pools its best for one enormous gamble.",
    ),
}

CARAVAN_ROUTE_ORDER = ["local_run", "merchant_caravan", "grand_expedition", "legendary_venture"]

assert len(CARAVAN_ROUTES) == len(CARAVAN_ROUTE_ORDER) == 4
