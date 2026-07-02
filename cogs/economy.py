"""Coin purse: balance, daily stipend, payments, profile, leaderboards."""

from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from econ.jobs import JOBS, tool_name
from econ.utils import fmt_gold, progress_bar, xp_needed

DAILY_BASE = 100
DAILY_STREAK_BONUS = 10
DAILY_STREAK_CAP = 10


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @app_commands.command(name="balance", description="Count the coin in your purse")
    @app_commands.guild_only()
    @app_commands.describe(member="Whose purse to peek at (default: you)")
    async def balance(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        target = member or interaction.user
        user = await self.db.get_user(interaction.guild_id, target.id)
        embed = discord.Embed(
            title=f"💰 {target.display_name}'s Purse",
            description=f"**{fmt_gold(user['gold'])}**",
            colour=discord.Colour.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="daily", description="Collect your daily stipend from the town coffers")
    @app_commands.guild_only()
    async def daily(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        user = await self.db.get_user(gid, uid)
        today = date.today()

        if user["last_daily"] == today.isoformat():
            await interaction.response.send_message(
                "🕯️ The coffers open but once a day. Return on the morrow!",
                ephemeral=True,
            )
            return

        yesterday = (today - timedelta(days=1)).isoformat()
        streak = user["daily_streak"] + 1 if user["last_daily"] == yesterday else 1
        bonus = min(streak - 1, DAILY_STREAK_CAP) * DAILY_STREAK_BONUS
        payout = DAILY_BASE + bonus

        await self.db.set_daily(gid, uid, today.isoformat(), streak)
        balance = await self.db.add_gold(gid, uid, payout)

        embed = discord.Embed(
            title="🏛️ Daily Stipend",
            description=(
                f"The town treasurer hands you **{fmt_gold(payout)}**."
                + (f"\n🔥 Streak: **{streak}** days (+{fmt_gold(bonus)})" if bonus else "")
            ),
            colour=discord.Colour.gold(),
        )
        embed.set_footer(text=f"Purse: {balance:,} gold")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pay", description="Hand coin to another townsfolk")
    @app_commands.guild_only()
    @app_commands.describe(member="Who receives the coin", amount="How much gold to give")
    async def pay(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        amount: app_commands.Range[int, 1],
    ):
        if member.bot or member.id == interaction.user.id:
            await interaction.response.send_message(
                "You cannot pay yourself or a construct of gears and magic.",
                ephemeral=True,
            )
            return
        ok = await self.db.transfer_gold(
            interaction.guild_id, interaction.user.id, member.id, amount
        )
        if not ok:
            await interaction.response.send_message(
                "Your purse is too light for that.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🤝 {interaction.user.mention} hands **{fmt_gold(amount)}** "
            f"to {member.mention}."
        )

    @app_commands.command(name="profile", description="Your standing in the town")
    @app_commands.guild_only()
    @app_commands.describe(member="Whose profile to view (default: you)")
    async def profile(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        target = member or interaction.user
        gid = interaction.guild_id
        user = await self.db.get_user(gid, target.id)
        inventory = await self.db.get_inventory(gid, target.id)
        total_items = sum(row["qty"] for row in inventory)

        embed = discord.Embed(
            title=f"🏰 {target.display_name} of the Town",
            colour=discord.Colour.dark_gold(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="💰 Purse", value=fmt_gold(user["gold"]), inline=True)

        if user["job"]:
            info = JOBS[user["job"]]
            skill = await self.db.get_skill(gid, target.id, user["job"])
            tier = await self.db.get_tool_tier(gid, target.id, user["job"])
            needed = xp_needed(skill["level"])
            embed.add_field(
                name="⚒️ Trade",
                value=f"{info['emoji']} {info['name']} — Lv. **{skill['level']}**",
                inline=True,
            )
            embed.add_field(name="🔧 Tool", value=tool_name(user["job"], tier), inline=True)
            embed.add_field(
                name="📈 Progress",
                value=f"`{progress_bar(skill['xp'], needed)}` {skill['xp']}/{needed} XP",
                inline=False,
            )
        else:
            embed.add_field(name="⚒️ Trade", value="*Unemployed wanderer*", inline=True)

        embed.add_field(
            name="🎒 Satchel", value=f"{total_items:,} goods", inline=True
        )
        if user["daily_streak"]:
            embed.add_field(
                name="🔥 Daily streak", value=f"{user['daily_streak']} days", inline=True
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="The wealthiest and most skilled in town")
    @app_commands.guild_only()
    @app_commands.describe(board="Which ranking to view")
    @app_commands.choices(
        board=[
            app_commands.Choice(name="💰 Richest townsfolk", value="gold"),
            app_commands.Choice(name="📖 Most skilled", value="skills"),
        ]
    )
    async def leaderboard(
        self, interaction: discord.Interaction, board: str = "gold"
    ):
        gid = interaction.guild_id
        if board == "skills":
            rows = await self.db.top_skills(gid)
            title = "📖 Most Skilled Townsfolk"
            lines = [
                f"**{i}.** <@{row['user_id']}> — {row['total_level']} total levels"
                for i, row in enumerate(rows, 1)
            ]
        else:
            rows = await self.db.top_gold(gid)
            title = "💰 Richest Townsfolk"
            lines = [
                f"**{i}.** <@{row['user_id']}> — {fmt_gold(row['gold'])}"
                for i, row in enumerate(rows, 1)
            ]
        embed = discord.Embed(
            title=title,
            description="\n".join(lines) or "*The town ledger is empty.*",
            colour=discord.Colour.gold(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
