"""The satchel, the town market (selling), and the smithy (tools)."""

from __future__ import annotations

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import formulas
from econ.data.consumables import CONSUMABLES
from econ.data.items import ITEMS, item_label, rarity_badge
from econ.data.jobs import JOBS
from econ.data.recipes import RECIPES
from econ.data.store import (
    RARE_POOL,
    RARE_STOCK_SIZE,
    STORE_CONSUMABLE_MARKUP,
    STORE_RARE_MARKUP,
    STORE_STOCK_RANGE_CONSUMABLE,
    STORE_STOCK_RANGE_RARE,
)
from econ.data.tools import MAX_TOOL_TIER, TOOLS, tool_name, tool_price
from ui.panels import AMT_W, NAME_W, QTY_W, TOOL_W, Palette, Panel, chip, simple_panel


def resolve_item(query: str) -> str | None:
    """Fuzzy-match a user-typed item name ('wheat', 'Iron Ore', 'iron')."""
    q = query.strip().lower().replace(" ", "_")
    if q in ITEMS:
        return q
    q = query.strip().lower()
    for key, info in ITEMS.items():
        if info["name"].lower() == q:
            return key
    for key, info in ITEMS.items():
        if info["name"].lower().startswith(q) or key.startswith(q.replace(" ", "_")):
            return key
    return None


def _market_categories() -> list[tuple[str, str, str, list[str]]]:
    """One (key, emoji, name, item_keys) entry per trade with goods to
    price, plus a Crafted Goods entry -- what .market's category picker
    browses, one at a time instead of one giant wall of every trade."""
    cats = []
    for job_key, info in JOBS.items():
        if not info["yields"]:
            continue  # Criminal deals in gold only, no goods to price
        item_keys = [item for item, *_rest in info["yields"]]
        cats.append((job_key, info["emoji"], info["name"], item_keys))
    craft_items = [r["output_item"] for r in RECIPES.values()]
    cats.append(("crafted", "🛠️", "Crafted Goods", craft_items))
    return cats


def _inventory_categories() -> list[tuple[str, str, str, list[str] | None]]:
    """.inventory's category picker: everything you carry, a cross-cutting
    view of just your usable consumables, then one trade at a time --
    same shape as .market's picker so both feel familiar. `None` for
    item_keys means "whatever you happen to own", not a fixed list."""
    cats = [("all", "🎒", "All Items", None)]
    cats.append(("consumables", "✨", "Consumables", list(CONSUMABLES.keys())))
    cats.extend(_market_categories())
    return cats


class Market(commands.Cog):
    """Where goods become gold."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ══════════════════════════ inventory ══════════════════════════════

    def _build_inventory_panel(
        self, category_key: str, owned: dict[str, int], display_name: str,
        author_id: int, target_id: int,
    ) -> Panel:
        cats = _inventory_categories()
        by_key = {key: (emoji, name, items) for key, emoji, name, items in cats}
        emoji, name, fixed_items = by_key[category_key]

        item_keys = list(owned.keys()) if fixed_items is None else [
            i for i in fixed_items if owned.get(i, 0) > 0
        ]
        item_keys.sort(
            key=lambda i: formulas.market_price(i, ITEMS[i]["value"]) * owned[i],
            reverse=True,
        )

        panel = Panel(author_id=author_id, timeout=180)
        panel.header(f"🎒 {display_name}'s Satchel · {emoji} {name}")
        if not item_keys:
            panel.text(
                "*Nothing here yet.*" if category_key != "all"
                else "*Empty as a beggar's bowl. Go `.work`!*"
            )
            panel.footer("Worth 0 gold today")
        else:
            total = 0
            lines = []
            any_usable = False
            for item in item_keys:
                info_i = ITEMS[item]
                price = formulas.market_price(item, info_i["value"])
                qty = owned[item]
                worth = price * qty
                total += worth
                buff = CONSUMABLES.get(item)
                if category_key == "consumables" and buff:
                    lines.append(
                        f"{info_i['emoji']} "
                        f"{chip((info_i['name'], NAME_W), (f'x{qty}', -QTY_W))}\n"
                        f"　✨ {buff['description']}"
                    )
                else:
                    # The usable marker lives INSIDE the fixed-width chip:
                    # anything trailing after the coin emoji wraps onto its
                    # own line on narrow (mobile) screens and renders as a
                    # stray symbol floating between rows.
                    item_name = info_i["name"]
                    if buff:
                        any_usable = True
                        item_name = f"{item_name[:NAME_W - 2].rstrip()} *"
                    lines.append(
                        f"{info_i['emoji']} "
                        f"{chip((item_name, NAME_W), (f'x{qty}', QTY_W), (f'{worth:,}', -AMT_W))} 🪙"
                    )
            panel.text("\n".join(lines))
            footer = f"Worth {total:,} gold today"
            if any_usable:
                footer += " · `*` usable with `.use`"
            panel.footer(footer)

        select = ui.Select(placeholder="🎒 Browse a category…")
        for key, e, n, _items in cats:
            select.add_option(label=n, value=key, emoji=e, default=(key == category_key))
        select.callback = self._make_inventory_select_handler(target_id, display_name)
        panel.select(select)
        return panel

    @commands.hybrid_command(name="inventory", aliases=["inv", "satchel"], description="Look inside a satchel")
    @commands.guild_only()
    @app_commands.describe(member="Whose satchel to look inside (default: you)")
    async def inventory(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        rows = await self.db.get_inventory(ctx.guild.id, target.id)
        owned = {r["item"]: r["qty"] for r in rows if r["item"] in ITEMS}
        panel = self._build_inventory_panel(
            "all", owned, target.display_name, ctx.author.id, target.id
        )
        panel.message = await ctx.send(view=panel)

    def _make_inventory_select_handler(self, target_id: int, display_name: str):
        """Bound to whichever satchel the panel is showing, so switching
        category with the dropdown keeps browsing THAT satchel -- not
        silently flipping to the clicker's own once someone else's
        `.inventory <member>` panel is on screen (the panel's author_id
        already restricts clicks to whoever ran the command)."""
        async def handler(interaction: discord.Interaction) -> None:
            category_key = interaction.data["values"][0]
            rows = await self.db.get_inventory(interaction.guild_id, target_id)
            owned = {r["item"]: r["qty"] for r in rows if r["item"] in ITEMS}
            panel = self._build_inventory_panel(
                category_key, owned, display_name, interaction.user.id, target_id
            )
            panel.message = interaction.message
            await interaction.response.edit_message(view=panel)
        return handler

    # ══════════════════════════ the market ═════════════════════════════

    def _build_market_panel(self, category_key: str, author_id: int) -> Panel:
        cats = _market_categories()
        by_key = {key: (emoji, name, items) for key, emoji, name, items in cats}
        emoji, name, item_keys = by_key[category_key]

        panel = Panel(author_id=author_id, timeout=180)
        panel.header(f"🏪 The Town Market · {emoji} {name}")
        lines = []
        for item in item_keys:
            base = ITEMS[item]["value"]
            price = formulas.market_price(item, base)
            arrow = " ▲" if price > base else (" ▼" if price < base else "")
            lines.append(
                f"{ITEMS[item]['emoji']} "
                f"{chip((ITEMS[item]['name'], NAME_W), (f'{price:,}', -AMT_W))} 🪙{arrow}"
            )
        panel.text("\n".join(lines))
        panel.footer("▲ above usual · ▼ below")

        select = ui.Select(placeholder="🏪 Browse a category…")
        for key, e, n, _items in cats:
            select.add_option(label=n, value=key, emoji=e, default=(key == category_key))
        select.callback = self._market_select
        panel.select(select)
        return panel

    @commands.hybrid_command(name="market", aliases=["prices"], description="Today's prices at the town market")
    @commands.guild_only()
    async def market(self, ctx: commands.Context):
        default_key = _market_categories()[0][0]
        panel = self._build_market_panel(default_key, ctx.author.id)
        panel.message = await ctx.send(view=panel)

    async def _market_select(self, interaction: discord.Interaction) -> None:
        category_key = interaction.data["values"][0]
        panel = self._build_market_panel(category_key, interaction.user.id)
        panel.message = interaction.message
        await interaction.response.edit_message(view=panel)

    async def _sell_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        rows = await self.db.get_inventory(interaction.guild_id, interaction.user.id)
        q = current.lower()
        choices = [
            app_commands.Choice(
                name=f"{ITEMS[row['item']]['name']} ({row['qty']})", value=row["item"]
            )
            for row in rows
            if row["item"] in ITEMS and q in ITEMS[row["item"]]["name"].lower()
        ]
        if not current:
            choices.insert(0, app_commands.Choice(name="✨ Everything", value="all"))
        return choices[:25]

    @commands.hybrid_command(name="sell", description="Sell goods at the town market")
    @commands.guild_only()
    @app_commands.describe(
        item="What to sell, or 'all' for everything (default)",
        amount="How many to sell (default: all of that item)",
    )
    @app_commands.autocomplete(item=_sell_item_autocomplete)
    async def sell(
        self,
        ctx: commands.Context,
        item: str | None = None,
        amount: commands.Range[int, 1] | None = None,
    ):
        gid, uid = ctx.guild.id, ctx.author.id

        if item is None or item.lower() in ("all", "everything"):
            await self._send_sell_all_confirm(ctx)
            return

        item_key = resolve_item(item)
        if item_key is None:
            await ctx.send(
                view=simple_panel(
                    f"The merchants squint at **{item}**. No such goods "
                    "are traded here.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        have = await self.db.get_item_qty(gid, uid, item_key)
        if have <= 0:
            await ctx.send(
                view=simple_panel(
                    f"You carry no {item_label(item_key)}.", accent=Palette.RED
                ),
                ephemeral=True,
            )
            return

        qty = min(amount, have) if amount else have
        price = formulas.market_price(item_key, ITEMS[item_key]["value"])
        earned = price * qty
        if not await self.db.remove_item(gid, uid, item_key, qty):
            await ctx.send(
                view=simple_panel(
                    "Those goods are already gone from your satchel.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        balance = await self.db.add_gold(gid, uid, earned)
        await self.db.incr_stat(gid, uid, "items_sold", qty)
        await self.db.incr_stat(gid, uid, "gold_from_sales", earned)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏪 Sold!")
        panel.text(
            f"{ITEMS[item_key]['emoji']} "
            f"{chip((ITEMS[item_key]['name'], NAME_W), (f'x{qty}', QTY_W), (f'{earned:,}', -AMT_W))} 🪙"
        )
        panel.footer(f"{price:,} gold each · Purse: {balance:,} gold")
        await ctx.send(view=panel)

    async def _send_sell_all_confirm(self, ctx: commands.Context) -> None:
        """.sell with no item is destructive (empties the whole satchel
        at once), so it gets an "are you sure?" step first instead of
        firing immediately."""
        gid, uid = ctx.guild.id, ctx.author.id
        rows = [r for r in await self.db.get_inventory(gid, uid) if r["item"] in ITEMS]
        if not rows:
            await ctx.send(
                view=simple_panel(
                    "You have nothing to sell. Go `.work` first!", accent=Palette.RED
                ),
                ephemeral=True,
            )
            return
        count = sum(r["qty"] for r in rows)
        total = sum(
            formulas.market_price(r["item"], ITEMS[r["item"]]["value"]) * r["qty"]
            for r in rows
        )

        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=30)
        panel.header("🏪 Sell Everything?")
        panel.text(
            f"This sells your whole satchel, **{count:,}** items for "
            f"roughly **{total:,} 🪙**. This can't be undone."
        )
        yes_btn = ui.Button(label="Sell Everything", emoji="🏪", style=discord.ButtonStyle.danger)
        no_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)

        async def on_yes(interaction: discord.Interaction) -> None:
            result = await self.build_sell_all_panel(interaction.guild_id, interaction.user.id)
            if isinstance(result, str):
                await interaction.response.edit_message(
                    view=simple_panel(result, accent=Palette.RED)
                )
                return
            await interaction.response.edit_message(view=result)

        async def on_no(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(
                view=simple_panel(
                    "Sale cancelled, your satchel is untouched.", accent=Palette.GOLD
                )
            )

        yes_btn.callback = on_yes
        no_btn.callback = on_no
        panel.buttons(yes_btn, no_btn)
        panel.message = await ctx.send(view=panel)

    async def build_sell_all_panel(self, gid: int, uid: int) -> Panel | str:
        """Sell the whole satchel. Returns a result Panel, or an error
        string. Gated behind a confirm step by .sell (_send_sell_all_confirm)
        since it's a one-shot, irreversible action."""
        rows = [
            r for r in await self.db.get_inventory(gid, uid) if r["item"] in ITEMS
        ]
        if not rows:
            return "You have nothing to sell. Go `.work` first!"
        total, count, lines = 0, 0, []
        for row in rows:
            info_i = ITEMS[row["item"]]
            price = formulas.market_price(row["item"], info_i["value"])
            qty = row["qty"]
            earned = price * qty
            if not await self.db.remove_item(gid, uid, row["item"], qty):
                continue  # spent between the confirm and now; skip it
            total += earned
            count += qty
            lines.append(
                f"{info_i['emoji']} "
                f"{chip((info_i['name'], NAME_W), (f'x{qty}', QTY_W), (f'{earned:,}', -AMT_W))} 🪙"
            )
        if not lines:
            return "You have nothing to sell. Go `.work` first!"
        balance = await self.db.add_gold(gid, uid, total)
        await self.db.incr_stat(gid, uid, "items_sold", count)
        await self.db.incr_stat(gid, uid, "gold_from_sales", total)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏪 Everything Sold!")
        panel.text("\n".join(lines))
        panel.divider()
        panel.text(
            f"💰 {chip(('Total', NAME_W), ('', QTY_W), (f'{total:,}', -AMT_W))} 🪙"
        )
        panel.footer(f"Purse: {balance:,} gold")
        return panel

    async def build_sell_items_panel(
        self, gid: int, uid: int, items: list[tuple[str, int]]
    ) -> Panel | str:
        """Sell exactly the given (item, qty) pairs -- used by the Sell
        Haul button on a .work result, so it only sells what that one
        work just brought in, not the whole satchel. Capped at whatever
        is still actually held, in case some was already sold or spent
        by hand before the button was pressed."""
        total, count, lines = 0, 0, []
        for item, qty in items:
            if item not in ITEMS:
                continue
            have = await self.db.get_item_qty(gid, uid, item)
            sell_qty = min(qty, have)
            if sell_qty <= 0:
                continue
            info_i = ITEMS[item]
            price = formulas.market_price(item, info_i["value"])
            earned = price * sell_qty
            if not await self.db.remove_item(gid, uid, item, sell_qty):
                continue  # sold or spent since the button was rendered
            total += earned
            count += sell_qty
            lines.append(
                f"{info_i['emoji']} "
                f"{chip((info_i['name'], NAME_W), (f'x{sell_qty}', QTY_W), (f'{earned:,}', -AMT_W))} 🪙"
            )
        if not lines:
            return "That haul is already gone, nothing left of it to sell."
        balance = await self.db.add_gold(gid, uid, total)
        await self.db.incr_stat(gid, uid, "items_sold", count)
        await self.db.incr_stat(gid, uid, "gold_from_sales", total)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏪 Haul Sold!")
        panel.text("\n".join(lines))
        panel.divider()
        panel.text(
            f"💰 {chip(('Total', NAME_W), ('', QTY_W), (f'{total:,}', -AMT_W))} 🪙"
        )
        panel.footer(f"Purse: {balance:,} gold")
        return panel

    # ══════════════════════════ the smithy ═════════════════════════════

    async def _fill_job_store(self, panel: Panel, gid: int, uid: int) -> ui.Button | None:
        """Renders the tool ladder for whichever trade the player
        currently holds into `panel` (header/text/footer), returning a
        'buy next tier' button to attach -- or None if there's no job,
        or nothing left to buy. Shared by .shop and .store's Job Store
        tab, so there's exactly one place that knows how to draw this."""
        user = await self.db.get_user(gid, uid)
        if not user["job"]:
            panel.header("⚒️ The Smithy")
            panel.text(
                "The smith only sells to working folk. Take a trade "
                "with `.job` first."
            )
            return None
        job_key = user["job"]
        info = JOBS[job_key]
        tier = await self.db.get_tool_tier(gid, uid, job_key)

        panel.header(f"⚒️ The Smithy · {info['emoji']} {info['name']}")
        panel.text(
            f"You carry: **{tool_name(job_key, tier)}** "
            f"*(×{formulas.tool_multiplier(tier):.2f})*"
        )
        lines = []
        for t in range(1, MAX_TOOL_TIER + 1):
            name = TOOLS[job_key][t - 1]
            if t <= tier:
                lines.append(f"✅ {chip((name, TOOL_W), ('owned', -AMT_W))}")
            else:
                icon = "⚒️" if t == tier + 1 else "🔒"
                lines.append(
                    f"{icon} {chip((name, TOOL_W), (f'{tool_price(t):,}', -AMT_W))} 🪙"
                )
        panel.text("\n".join(lines))
        panel.footer(f"Your purse: {user['gold']:,} gold")

        if tier >= MAX_TOOL_TIER:
            return None
        next_name = TOOLS[job_key][tier]
        next_mult = formulas.tool_multiplier(tier + 1)
        buy_btn = ui.Button(
            label=f"Buy {next_name} · ×{next_mult:.2f} · {tool_price(tier + 1):,} gold",
            emoji="⚒️",
            style=discord.ButtonStyle.primary,
        )
        buy_btn.callback = self._buy_button
        return buy_btn

    @commands.hybrid_command(
        name="shop", aliases=["smithy"],
        description="Browse tools for your trade, or switch to the general store",
    )
    @commands.guild_only()
    async def shop(self, ctx: commands.Context):
        # Same dropdown-driven panel .store shows, just opened on the
        # Job Store tab by default -- .store opens on General Store by
        # default. Same two tabs either way, just a different door in.
        panel = await self._build_store_panel("jobstore", ctx.guild.id, ctx.author.id)
        panel.message = await ctx.send(view=panel)

    async def _buy_button(self, interaction: discord.Interaction) -> None:
        panel = await self._buy_next_tool(interaction.guild_id, interaction.user)
        await interaction.response.send_message(
            view=panel, ephemeral=getattr(panel, "is_error", False)
        )

    async def _buy_next_tool(
        self, guild_id: int, member: discord.abc.User
    ) -> Panel:
        user = await self.db.get_user(guild_id, member.id)
        if not user["job"]:
            panel = simple_panel("Take a trade first with `.job`.", accent=Palette.RED)
            panel.is_error = True
            return panel
        job_key = user["job"]
        tier = await self.db.get_tool_tier(guild_id, member.id, job_key)
        if tier >= MAX_TOOL_TIER:
            panel = simple_panel(
                "You already own the finest tool a master could wish for!",
                accent=Palette.RED,
            )
            panel.is_error = True
            return panel
        name = TOOLS[job_key][tier]
        price = tool_price(tier + 1)
        if not await self.db.spend_gold(guild_id, member.id, price):
            panel = simple_panel(
                f"**{name}** costs {formulas.fmt_gold(price)}, but your purse "
                f"holds only {formulas.fmt_gold(user['gold'])}.",
                accent=Palette.RED,
            )
            panel.is_error = True
            return panel

        await self.db.set_tool_tier(guild_id, member.id, job_key, tier + 1)
        await self.db.incr_stat(guild_id, member.id, "gold_spent_tools", price)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.is_error = False
        panel.header("⚒️ A Fine Purchase!")
        panel.text(
            f"The smith hands {member.mention} a **{name}** for "
            f"{formulas.fmt_gold(price)}.\n"
            f"Yields are now **×{formulas.tool_multiplier(tier + 1):.2f}** from tools alone."
        )
        return panel

    @commands.hybrid_command(name="buy", description="Buy the next tool tier for your trade")
    @commands.guild_only()
    async def buy(self, ctx: commands.Context):
        panel = await self._buy_next_tool(ctx.guild.id, ctx.author)
        await ctx.send(view=panel, ephemeral=getattr(panel, "is_error", False))

    # ══════════════════════════ the general store ══════════════════════
    # .store: a second dropdown-driven browser, same shape as .market
    # and .inventory. General Store sells potions/foods and a daily
    # rotation of rare raw goods, all at a flat markup over their base
    # value (see econ/data/store.py). Job Store just re-renders
    # _fill_job_store -- the exact same content .shop shows -- so
    # there's one place, not two, that ever needs to change.

    async def _fill_general_store(
        self, panel: Panel, gid: int, uid: int
    ) -> ui.Select | None:
        user = await self.db.get_user(gid, uid)
        day = formulas.utc_day()
        bought_today = await self.db.get_store_purchases_today(gid, uid, day)
        panel.header("🏬 The General Store")
        panel.text("*Ready-made goods, for those who'd rather pay gold than gather.*")

        buy_select = ui.Select(placeholder="🛒 Buy an item…")

        # Stock isn't a flat number: it's rolled per (player, item, day),
        # so the same potion can show 1 in stock for you and 2 for
        # someone else, and neither of you sees the same number twice
        # in a row (see formulas.store_daily_limit).
        potion_lines = []
        for key, buff in CONSUMABLES.items():
            info = ITEMS[key]
            price = round(info["value"] * STORE_CONSUMABLE_MARKUP)
            stock = formulas.store_daily_limit(uid, key, day, *STORE_STOCK_RANGE_CONSUMABLE)
            left = stock - bought_today.get(key, 0)
            if left <= 0:
                potion_lines.append(f"{info['emoji']} **{info['name']}** · maxed for today")
                continue
            potion_lines.append(
                f"{info['emoji']} **{info['name']}** ({left} in stock) · {price:,} 🪙\n"
                f"　✨ {buff['description']}"
            )
            buy_select.add_option(
                label=f"{info['name']} · {price:,}g"[:100], value=key, emoji=info["emoji"],
                description=f"{left} left today · {buff['description']}"[:100],
            )
        panel.field("✨ Potions & Foods", "\n".join(potion_lines))

        rare_keys = formulas.store_rare_stock(RARE_POOL, RARE_STOCK_SIZE)
        rare_lines = []
        for key in rare_keys:
            info = ITEMS[key]
            price = round(info["value"] * STORE_RARE_MARKUP)
            badge = rarity_badge(key).strip()
            stock = formulas.store_daily_limit(uid, key, day, *STORE_STOCK_RANGE_RARE)
            left = stock - bought_today.get(key, 0)
            if left <= 0:
                rare_lines.append(f"{info['emoji']} **{info['name']}** · maxed for today")
                continue
            rare_lines.append(
                f"{info['emoji']} **{info['name']}** ({left} in stock) · {price:,} 🪙"
                + (f" {badge}" if badge else "")
            )
            buy_select.add_option(
                label=f"{info['name']} · {price:,}g"[:100], value=key, emoji=info["emoji"],
                description=f"{left} left today · today's rare stock"[:100],
            )
        panel.field("🌟 Rare Goods (today only)", "\n".join(rare_lines))
        panel.footer(
            f"Your purse: {user['gold']:,} gold · flat prices, not the daily market\n"
            "stock is random per player per item · resets at UTC midnight"
        )

        if not buy_select.options:
            return None
        buy_select.callback = self._store_buy_select
        return buy_select

    def _build_store_top_select(self, section: str) -> ui.Select:
        select = ui.Select(placeholder="🏬 Browse…")
        select.add_option(
            label="General Store", value="general", emoji="🏬",
            description="Potions, foods, and today's rare goods",
            default=(section == "general"),
        )
        select.add_option(
            label="Job Store", value="jobstore", emoji="⚒️",
            description="Tool tiers for your current trade",
            default=(section == "jobstore"),
        )
        select.callback = self._store_top_select
        return select

    async def _build_store_panel(self, section: str, gid: int, uid: int) -> Panel:
        accent = Palette.GOLD if section == "general" else Palette.IRON
        panel = Panel(accent=accent, author_id=uid, timeout=180)

        if section == "jobstore":
            extra = await self._fill_job_store(panel, gid, uid)
        else:
            extra = await self._fill_general_store(panel, gid, uid)

        if isinstance(extra, ui.Select):
            panel.select(extra)
        elif extra is not None:
            panel.buttons(extra)
        panel.select(self._build_store_top_select(section))
        return panel

    @commands.hybrid_command(
        name="store", description="The general store, and your trade's tool ladder"
    )
    @commands.guild_only()
    async def store(self, ctx: commands.Context):
        panel = await self._build_store_panel("general", ctx.guild.id, ctx.author.id)
        panel.message = await ctx.send(view=panel)

    async def _store_top_select(self, interaction: discord.Interaction) -> None:
        section = interaction.data["values"][0]
        panel = await self._build_store_panel(
            section, interaction.guild_id, interaction.user.id
        )
        panel.message = interaction.message
        await interaction.response.edit_message(view=panel)

    async def _store_buy_select(self, interaction: discord.Interaction) -> None:
        item_key = interaction.data["values"][0]
        gid, uid = interaction.guild_id, interaction.user.id
        info = ITEMS[item_key]
        is_consumable = item_key in CONSUMABLES
        day = formulas.utc_day()

        if is_consumable:
            price = round(info["value"] * STORE_CONSUMABLE_MARKUP)
            limit = formulas.store_daily_limit(uid, item_key, day, *STORE_STOCK_RANGE_CONSUMABLE)
        else:
            # Re-check against today's stock: the rotation can only
            # ever change at UTC midnight, but a stale panel viewed
            # right across that boundary shouldn't be able to buy
            # yesterday's rare goods.
            if item_key not in formulas.store_rare_stock(RARE_POOL, RARE_STOCK_SIZE):
                await interaction.response.edit_message(
                    view=simple_panel(
                        "That rare stock has already turned over for the "
                        "day. Run `.store` again to see what's in today.",
                        accent=Palette.RED,
                    )
                )
                return
            price = round(info["value"] * STORE_RARE_MARKUP)
            limit = formulas.store_daily_limit(uid, item_key, day, *STORE_STOCK_RANGE_RARE)

        # Reserve the day's purchase slot before spending gold, so a
        # stale select (rendered before today's limit was reached, or
        # raced by a second rapid click) can't be used to buy past the
        # cap. If paying then fails, release the slot back.
        if not await self.db.try_reserve_store_purchase(gid, uid, item_key, day, 1, limit):
            await interaction.response.edit_message(
                view=simple_panel(
                    f"You've already bought your limit of **{info['name']}** "
                    "for today. Check back after UTC midnight.",
                    accent=Palette.RED,
                )
            )
            return

        if not await self.db.spend_gold(gid, uid, price):
            await self.db.release_store_purchase(gid, uid, item_key, day, 1)
            user = await self.db.get_user(gid, uid)
            await interaction.response.edit_message(
                view=simple_panel(
                    f"**{info['name']}** costs {formulas.fmt_gold(price)}, but "
                    f"your purse holds only {formulas.fmt_gold(user['gold'])}.",
                    accent=Palette.RED,
                )
            )
            return

        await self.db.add_item(gid, uid, item_key, 1)
        await self.db.incr_stat(gid, uid, "gold_spent_store", price)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏬 Purchased!")
        panel.text(
            f"{info['emoji']} {chip((info['name'], NAME_W), ('+1', -QTY_W))} "
            f"for {formulas.fmt_gold(price)}"
        )
        if is_consumable:
            panel.text(f"✨ {CONSUMABLES[item_key]['description']} · usable with `.use`")
        else:
            badge = rarity_badge(item_key).strip()
            panel.text(f"{badge} Straight into your satchel." if badge else "Straight into your satchel.")
        await interaction.response.edit_message(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Market(bot))
