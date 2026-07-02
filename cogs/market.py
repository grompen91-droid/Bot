"""Inventory, the town market (selling), and the tool shop."""

import discord
from discord import app_commands
from discord.ext import commands

from econ.jobs import ITEMS, JOBS, TOOLS, tool_multiplier, tool_name
from econ.utils import fmt_gold, item_label, market_price


class Market(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @app_commands.command(name="inventory", description="Look inside your satchel")
    @app_commands.guild_only()
    async def inventory(self, interaction: discord.Interaction):
        rows = await self.db.get_inventory(interaction.guild_id, interaction.user.id)
        embed = discord.Embed(
            title=f"🎒 {interaction.user.display_name}'s Satchel",
            colour=discord.Colour.dark_teal(),
        )
        if not rows:
            embed.description = "Empty as a beggar's bowl. Go `/work`!"
        else:
            lines, total = [], 0
            for row in rows:
                if row["item"] not in ITEMS:
                    continue
                price = market_price(row["item"])
                worth = price * row["qty"]
                total += worth
                lines.append(
                    f"{item_label(row['item'])} × **{row['qty']}** "
                    f"(worth ~{fmt_gold(worth)})"
                )
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"Total market value today: {total:,} gold")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="market", description="Today's prices at the town market")
    @app_commands.guild_only()
    async def market(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🏪 The Town Market",
            description="Prices shift with the winds each day. Sell with `/sell`.",
            colour=discord.Colour.dark_gold(),
        )
        for job_key, info in JOBS.items():
            lines = []
            for item, *_ in info["yields"]:
                price = market_price(item)
                base = ITEMS[item]["value"]
                arrow = "▲" if price > base else ("▼" if price < base else "•")
                lines.append(f"{item_label(item)} — {fmt_gold(price)} {arrow}")
            embed.add_field(
                name=f"{info['emoji']} {info['name']}'s goods",
                value="\n".join(lines),
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    async def _sell_item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        rows = await self.db.get_inventory(interaction.guild_id, interaction.user.id)
        current = current.lower()
        choices = [
            app_commands.Choice(
                name=f"{ITEMS[row['item']]['name']} ({row['qty']})", value=row["item"]
            )
            for row in rows
            if row["item"] in ITEMS and current in ITEMS[row["item"]]["name"].lower()
        ]
        return choices[:25]

    @app_commands.command(name="sell", description="Sell goods at the town market")
    @app_commands.guild_only()
    @app_commands.describe(
        item="What to sell (leave empty to sell everything)",
        amount="How many to sell (default: all of that item)",
    )
    @app_commands.autocomplete(item=_sell_item_autocomplete)
    async def sell(
        self,
        interaction: discord.Interaction,
        item: str | None = None,
        amount: app_commands.Range[int, 1] | None = None,
    ):
        gid, uid = interaction.guild_id, interaction.user.id

        if item is None:
            rows = await self.db.get_inventory(gid, uid)
            rows = [r for r in rows if r["item"] in ITEMS]
            if not rows:
                await interaction.response.send_message(
                    "You have nothing to sell. Go `/work` first!", ephemeral=True
                )
                return
            total, lines = 0, []
            for row in rows:
                price = market_price(row["item"])
                earned = price * row["qty"]
                await self.db.remove_item(gid, uid, row["item"], row["qty"])
                total += earned
                lines.append(f"{item_label(row['item'])} × {row['qty']} → {fmt_gold(earned)}")
            balance = await self.db.add_gold(gid, uid, total)
            embed = discord.Embed(
                title="🏪 Market Day — everything sold!",
                description="\n".join(lines),
                colour=discord.Colour.green(),
            )
            embed.add_field(name="Total earned", value=f"**{fmt_gold(total)}**")
            embed.set_footer(text=f"Purse: {balance:,} gold")
            await interaction.response.send_message(embed=embed)
            return

        if item not in ITEMS:
            await interaction.response.send_message(
                "The merchants squint at that — no such goods are traded here.",
                ephemeral=True,
            )
            return
        have = await self.db.get_item_qty(gid, uid, item)
        if have <= 0:
            await interaction.response.send_message(
                f"You carry no {ITEMS[item]['name']}.", ephemeral=True
            )
            return
        qty = min(amount, have) if amount else have
        price = market_price(item)
        earned = price * qty
        await self.db.remove_item(gid, uid, item, qty)
        balance = await self.db.add_gold(gid, uid, earned)
        embed = discord.Embed(
            title="🏪 Sold!",
            description=(
                f"{item_label(item)} × **{qty}** at {fmt_gold(price)} each "
                f"→ **{fmt_gold(earned)}**"
            ),
            colour=discord.Colour.green(),
        )
        embed.set_footer(text=f"Purse: {balance:,} gold")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="shop", description="Browse tools for your trade")
    @app_commands.guild_only()
    async def shop(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        user = await self.db.get_user(gid, uid)
        if not user["job"]:
            await interaction.response.send_message(
                "The smith only sells to working folk. Pick a trade with `/job choose`.",
                ephemeral=True,
            )
            return
        job_key = user["job"]
        info = JOBS[job_key]
        tier = await self.db.get_tool_tier(gid, uid, job_key)

        embed = discord.Embed(
            title=f"⚒️ The Smithy — {info['emoji']} {info['name']}'s tools",
            description=(
                f"You carry: **{tool_name(job_key, tier)}** "
                f"(×{tool_multiplier(tier):.2f} yield)\n"
                "Buy the next tier with `/buy`. Better tools mean bigger hauls."
            ),
            colour=discord.Colour.dark_grey(),
        )
        for i, (name, price) in enumerate(TOOLS[job_key], start=1):
            if i <= tier:
                status = "✅ owned"
            elif i == tier + 1:
                status = f"{fmt_gold(price)} — available now"
            else:
                status = f"{fmt_gold(price)} — 🔒 buy previous tier first"
            embed.add_field(
                name=f"Tier {i}: {name} (×{tool_multiplier(i):.2f})",
                value=status,
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="buy", description="Buy the next tool tier for your trade")
    @app_commands.guild_only()
    async def buy(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        user = await self.db.get_user(gid, uid)
        if not user["job"]:
            await interaction.response.send_message(
                "Pick a trade first with `/job choose`.", ephemeral=True
            )
            return
        job_key = user["job"]
        tier = await self.db.get_tool_tier(gid, uid, job_key)
        if tier >= len(TOOLS[job_key]):
            await interaction.response.send_message(
                "You already own the finest tool a master could wish for!",
                ephemeral=True,
            )
            return
        name, price = TOOLS[job_key][tier]
        if user["gold"] < price:
            await interaction.response.send_message(
                f"**{name}** costs {fmt_gold(price)}, but your purse holds only "
                f"{fmt_gold(user['gold'])}.",
                ephemeral=True,
            )
            return
        await self.db.add_gold(gid, uid, -price)
        await self.db.set_tool_tier(gid, uid, job_key, tier + 1)
        embed = discord.Embed(
            title="⚒️ A fine purchase!",
            description=(
                f"The smith hands you a **{name}** for {fmt_gold(price)}.\n"
                f"Your yields are now ×{tool_multiplier(tier + 1):.2f}."
            ),
            colour=discord.Colour.green(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Market(bot))
