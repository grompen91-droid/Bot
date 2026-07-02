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
        panel.header("🏛️ Daily Stipend")
        panel.text(f"# {formulas.fmt_gold(payout)}")
        extras = []
        if streak_bonus:
            extras.append(f"🔥 streak ×{streak}: +{streak_bonus:,}")
        if level_bonus:
            extras.append(f"📖 skill: +{level_bonus:,}")
        if extras:
            panel.text(" · ".join(extras))
        panel.footer(f"Purse: {balance:,} gold")
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
        total_level = await self.db.total_level(gid, target.id)

        if user["job"]:
            info = JOBS[user["job"]]
            skill = await self.db.get_skill(gid, target.id, user["job"])
            tier = await self.db.get_tool_tier(gid, target.id, user["job"])
            needed = formulas.xp_to_next(skill["level"])
            trade_lines = [
                f"{info['emoji']} **{info['name']}** Lv **{skill['level']}** · "
                f"🔧 {tool_name(user['job'], tier)}",
                f"`{formulas.progress_bar(skill['xp'], needed)}` "
                f"{skill['xp']}/{needed} XP",
            ]
        else:
            trade_lines = ["*No trade yet, see* `.job`"]

        rank_emoji, rank_title = formulas.town_rank(total_level)
        panel = Panel(timeout=None)
        panel.header(f"🏰 {target.display_name} of the Town")
        panel.section(
            f"{rank_emoji} **{rank_title}**",
            f"💰 **{formulas.fmt_gold(user['gold'])}**",
            thumbnail=target.display_avatar.url,
        )
        panel.text("\n".join(trade_lines))
        if user["daily_streak"]:
            panel.footer(f"🔥 {user['daily_streak']} day streak")
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
            lines = []
            for i, row in enumerate(rows):
                emoji, _title = formulas.town_rank(row["total_level"])
                lines.append(
                    f"{medals[i] if i < 3 else f'**{i + 1}.**'} <@{row['user_id']}> · "
                    f"**{row['total_level']}** levels {emoji}"
                )
        else:
            rows = await self.db.top_gold(gid)
            title = "💰 The Richest Townsfolk"
            lines = [
                f"{medals[i] if i < 3 else f'**{i + 1}.**'} <@{row['user_id']}> · "
                f"**{formulas.fmt_gold(row['gold'])}**"
                for i, row in enumerate(rows)
            ]
        panel = Panel(timeout=None)
        panel.header(title)
        panel.text("\n".join(lines) or "*The town ledger is empty.*")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
