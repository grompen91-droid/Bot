"""The satchel, the town market (selling), and the smithy (tools)."""

from __future__ import annotations

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import formulas
from econ.data.items import ITEMS, item_label
from econ.data.jobs import JOBS
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


class Market(commands.Cog):
    """Where goods become gold."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ══════════════════════════ inventory ══════════════════════════════

    @commands.hybrid_command(name="inventory", aliases=["inv", "satchel"], description="Look inside your satchel")
    @commands.guild_only()
    async def inventory(self, ctx: commands.Context):
        rows = await self.db.get_inventory(ctx.guild.id, ctx.author.id)
        rows = [r for r in rows if r["item"] in ITEMS]

        panel = Panel(timeout=None)
        panel.header(f"🎒 {ctx.author.display_name}'s Satchel")
        if not rows:
            panel.text("*Empty as a beggar's bowl. Go `.work`!*")
        else:
            rows.sort(key=lambda r: formulas.market_price(r["item"], ITEMS[r["item"]]["value"]) * r["qty"], reverse=True)
            total = 0
            lines = []
            for row in rows:
                info_i = ITEMS[row["item"]]
                price = formulas.market_price(row["item"], info_i["value"])
                qty = row["qty"]
                worth = price * qty
                total += worth
                lines.append(
                    f"{info_i['emoji']} "
                    f"{chip((info_i['name'], NAME_W), (f'x{qty}', QTY_W), (f'{worth:,}', -AMT_W))} 🪙"
                )
            panel.text("\n".join(lines))
            panel.footer(f"Worth {total:,} gold today")
        await ctx.send(view=panel)

    # ══════════════════════════ the market ═════════════════════════════

    @commands.hybrid_command(name="market", aliases=["prices"], description="Today's prices at the town market")
    @commands.guild_only()
    async def market(self, ctx: commands.Context):
        panel = Panel(timeout=None)
        panel.header("🏪 The Town Market")
        for job_key, info in JOBS.items():
            if not info["yields"]:
                continue  # Criminal deals in gold only, no goods to price
            lines = []
            for item, *_rest in info["yields"]:
                base = ITEMS[item]["value"]
                price = formulas.market_price(item, base)
                arrow = " ▲" if price > base else (" ▼" if price < base else "")
                lines.append(
                    f"{ITEMS[item]['emoji']} "
                    f"{chip((ITEMS[item]['name'], NAME_W), (f'{price:,}', -AMT_W))} 🪙{arrow}"
                )
            panel.field(f"{info['emoji']} {info['name']}", "\n".join(lines))
        panel.footer("▲ above usual · ▼ below")
        await ctx.send(view=panel)

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
            result = await self.build_sell_all_panel(gid, uid)
            if isinstance(result, str):
                await ctx.send(
                    view=simple_panel(result, accent=Palette.RED), ephemeral=True
                )
            else:
                await ctx.send(view=result)
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
        await self.db.remove_item(gid, uid, item_key, qty)
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

    async def build_sell_all_panel(self, gid: int, uid: int) -> Panel | str:
        """Sell the whole satchel. Returns a result Panel, or an error string.
        Also used by the Sell All button on work results."""
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
            await self.db.remove_item(gid, uid, row["item"], qty)
            total += earned
            count += qty
            lines.append(
                f"{info_i['emoji']} "
                f"{chip((info_i['name'], NAME_W), (f'x{qty}', QTY_W), (f'{earned:,}', -AMT_W))} 🪙"
            )
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
            await self.db.remove_item(gid, uid, item, sell_qty)
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

    @commands.hybrid_command(name="shop", aliases=["smithy"], description="Browse tools for your trade")
    @commands.guild_only()
    async def shop(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        if not user["job"]:
            await ctx.send(
                view=simple_panel(
                    "The smith only sells to working folk. Take a trade "
                    "with `.job` first.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        job_key = user["job"]
        info = JOBS[job_key]
        tier = await self.db.get_tool_tier(gid, uid, job_key)

        panel = Panel(accent=Palette.IRON, author_id=uid)
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

        if tier < MAX_TOOL_TIER:
            next_name = TOOLS[job_key][tier]
            next_mult = formulas.tool_multiplier(tier + 1)
            buy_btn = ui.Button(
                label=f"Buy {next_name} · ×{next_mult:.2f} · {tool_price(tier + 1):,} gold",
                emoji="⚒️",
                style=discord.ButtonStyle.primary,
            )
            buy_btn.callback = self._buy_button
            panel.buttons(buy_btn)
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
        if user["gold"] < price:
            panel = simple_panel(
                f"**{name}** costs {formulas.fmt_gold(price)}, but your purse "
                f"holds only {formulas.fmt_gold(user['gold'])}.",
                accent=Palette.RED,
            )
            panel.is_error = True
            return panel

        await self.db.add_gold(guild_id, member.id, -price)
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Market(bot))
