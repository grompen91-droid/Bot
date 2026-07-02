"""Coin purse: balance, daily stipend, payments, profile, leaderboards."""

from __future__ import annotations

from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from econ import formulas
from econ.data.jobs import JOBS
from econ.data.tools import tool_name
from ui.panels import Palette, Panel, simple_panel


class Economy(commands.Cog):
    """Gold in, gold out."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(name="balance", aliases=["bal", "gold"], description="Count the coin in a purse")
    @commands.guild_only()
    @app_commands.describe(member="Whose purse to peek at (default: you)")
    async def balance(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, target.id)
        panel = Panel(timeout=None)
        panel.header(f"💰 {target.display_name}'s Purse")
        panel.text(f"# {formulas.fmt_gold(user['gold'])}")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="daily", description="Collect your daily stipend from the town coffers")
    @commands.guild_only()
    async def daily(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        today = date.today()

        if user["last_daily"] == today.isoformat():
            await ctx.send(
                view=simple_panel(
                    "🕯️ The coffers open but once a day. Return on the morrow!",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        yesterday = (today - timedelta(days=1)).isoformat()
        streak = user["daily_streak"] + 1 if user["last_daily"] == yesterday else 1
        total_level = await self.db.total_level(gid, uid)
        payout, streak_bonus, level_bonus = formulas.daily_payout(streak, total_level)

        await self.db.set_daily(gid, uid, today.isoformat(), streak)
        balance = await self.db.add_gold(gid, uid, payout)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏛️ The Daily Stipend")
        panel.text(f"The town treasurer counts out **{formulas.fmt_gold(payout)}**.")
        details = [f"📜 Base stipend: {formulas.fmt_gold(formulas.DAILY_BASE)}"]
        if streak_bonus:
            details.append(
                f"🔥 Streak — **{streak}** days: +{formulas.fmt_gold(streak_bonus)}"
            )
        if level_bonus:
            details.append(
                f"📖 Renowned worker (Lv. {total_level} total): "
                f"+{formulas.fmt_gold(level_bonus)}"
            )
        panel.divider()
        panel.text("\n".join(details))
        panel.footer(f"Purse: {balance:,} gold · come back tomorrow to keep the streak")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="pay", description="Hand coin to another townsfolk")
    @commands.guild_only()
    @app_commands.describe(member="Who receives the coin", amount="How much gold to give")
    async def pay(
        self,
        ctx: commands.Context,
        member: discord.Member,
        amount: commands.Range[int, 1],
    ):
        if member.bot or member.id == ctx.author.id:
            await ctx.send(
                view=simple_panel(
                    "You cannot pay yourself, nor a construct of gears and magic.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        ok = await self.db.transfer_gold(ctx.guild.id, ctx.author.id, member.id, amount)
        if not ok:
            await ctx.send(
                view=simple_panel("Your purse is too light for that.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        await self.db.incr_stat(ctx.guild.id, ctx.author.id, "gold_gifted", amount)
        await ctx.send(
            view=simple_panel(
                f"🤝 {ctx.author.mention} hands **{formulas.fmt_gold(amount)}** "
                f"to {member.mention}.",
                accent=Palette.GREEN,
            )
        )

    @commands.hybrid_command(name="profile", description="Your standing in the town")
    @commands.guild_only()
    @app_commands.describe(member="Whose profile to view (default: you)")
    async def profile(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        gid = ctx.guild.id
        user = await self.db.get_user(gid, target.id)
        inventory = await self.db.get_inventory(gid, target.id)
        stats = await self.db.get_stats(gid, target.id)
        total_level = await self.db.total_level(gid, target.id)
        total_items = sum(row["qty"] for row in inventory)

        if user["job"]:
            info = JOBS[user["job"]]
            skill = await self.db.get_skill(gid, target.id, user["job"])
            tier = await self.db.get_tool_tier(gid, target.id, user["job"])
            needed = formulas.xp_to_next(skill["level"])
            trade_lines = [
                f"⚒️ **Trade:** {info['emoji']} {info['name']} — Lv. **{skill['level']}**",
                f"🔧 **Tool:** {tool_name(user['job'], tier)} "
                f"*(yields ×{formulas.total_multiplier(skill['level'], tier):.2f})*",
                f"`{formulas.progress_bar(skill['xp'], needed)}` "
                f"{skill['xp']}/{needed} XP",
            ]
        else:
            trade_lines = ["⚒️ **Trade:** *unemployed wanderer* — see `.job`"]

        panel = Panel(timeout=None)
        panel.header(f"🏰 {target.display_name} of the Town")
        panel.section(
            f"💰 **Purse:** {formulas.fmt_gold(user['gold'])}",
            f"📖 **Total skill level:** {total_level}",
            f"🎒 **Satchel:** {total_items:,} goods",
            thumbnail=target.display_avatar.url,
        )
        panel.divider()
        panel.text("\n".join(trade_lines))
        panel.divider()
        panel.field(
            "📜 Deeds",
            f"Days worked: **{stats.get('works', 0):,}** · "
            f"goods gathered: **{stats.get('items_gathered', 0):,}** · "
            f"goods sold: **{stats.get('items_sold', 0):,}**\n"
            f"Market earnings: **{formulas.fmt_gold(stats.get('gold_from_sales', 0))}** · "
            f"gifted away: **{formulas.fmt_gold(stats.get('gold_gifted', 0))}**",
        )
        if user["daily_streak"]:
            panel.footer(f"🔥 Daily streak: {user['daily_streak']} days")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="leaderboard", aliases=["lb", "top"], description="The wealthiest and most skilled in town")
    @commands.guild_only()
    @app_commands.describe(board="Which ranking to view")
    @app_commands.choices(
        board=[
            app_commands.Choice(name="💰 Richest townsfolk", value="gold"),
            app_commands.Choice(name="📖 Most skilled", value="skills"),
        ]
    )
    async def leaderboard(self, ctx: commands.Context, board: str = "gold"):
        gid = ctx.guild.id
        medals = ["🥇", "🥈", "🥉"]
        if board.lower().startswith("skill"):
            rows = await self.db.top_skills(gid)
            title = "📖 The Most Skilled Townsfolk"
            lines = [
                f"{medals[i] if i < 3 else f'**{i + 1}.**'} <@{row['user_id']}> — "
                f"**{row['total_level']}** total levels *(best: {row['best_level']})*"
                for i, row in enumerate(rows)
            ]
        else:
            rows = await self.db.top_gold(gid)
            title = "💰 The Richest Townsfolk"
            lines = [
                f"{medals[i] if i < 3 else f'**{i + 1}.**'} <@{row['user_id']}> — "
                f"**{formulas.fmt_gold(row['gold'])}**"
                for i, row in enumerate(rows)
            ]
        panel = Panel(timeout=None)
        panel.header(title)
        panel.text("\n".join(lines) or "*The town ledger is empty.*")
        panel.footer("try .leaderboard skills / .leaderboard gold")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
