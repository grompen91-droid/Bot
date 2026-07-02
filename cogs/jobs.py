"""Job picking, working, and skill progression."""

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from econ.jobs import JOBS, tool_multiplier, tool_name
from econ.utils import (
    apply_xp,
    fmt_gold,
    item_label,
    level_multiplier,
    progress_bar,
    xp_needed,
)

JOB_CHOICES = [
    app_commands.Choice(name=f"{info['emoji']} {info['name']}", value=key)
    for key, info in JOBS.items()
]


class Jobs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    job = app_commands.Group(
        name="job", description="Choose and manage your trade", guild_only=True
    )

    @job.command(name="list", description="See every trade the town offers")
    async def job_list(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 The Town Job Board",
            description="Choose a trade with `/job choose`. You may switch "
            "whenever you like — your skills are never forgotten.",
            colour=discord.Colour.dark_gold(),
        )
        for key, info in JOBS.items():
            embed.add_field(
                name=f"{info['emoji']} {info['name']}",
                value=f"{info['description']}\n⏳ Work every {info['cooldown']}s",
                inline=True,
            )
        await interaction.response.send_message(embed=embed)

    @job.command(name="choose", description="Take up a trade")
    @app_commands.describe(trade="The trade you wish to practise")
    @app_commands.choices(trade=JOB_CHOICES)
    async def job_choose(self, interaction: discord.Interaction, trade: str):
        user = await self.db.get_user(interaction.guild_id, interaction.user.id)
        info = JOBS[trade]
        if user["job"] == trade:
            await interaction.response.send_message(
                f"You are already working as a {info['emoji']} **{info['name']}**.",
                ephemeral=True,
            )
            return
        await self.db.set_job(interaction.guild_id, interaction.user.id, trade)
        skill = await self.db.get_skill(interaction.guild_id, interaction.user.id, trade)
        embed = discord.Embed(
            title=f"{info['emoji']} A new {info['name']} joins the town!",
            description=(
                f"{interaction.user.mention} takes up the {info['name'].lower()}'s "
                f"trade at skill level **{skill['level']}**.\n"
                f"Use `/work` to earn your keep."
            ),
            colour=discord.Colour.green(),
        )
        await interaction.response.send_message(embed=embed)

    @job.command(name="quit", description="Lay down your tools and quit your trade")
    async def job_quit(self, interaction: discord.Interaction):
        user = await self.db.get_user(interaction.guild_id, interaction.user.id)
        if not user["job"]:
            await interaction.response.send_message(
                "You have no trade to quit. See `/job list`.", ephemeral=True
            )
            return
        info = JOBS[user["job"]]
        await self.db.set_job(interaction.guild_id, interaction.user.id, None)
        await interaction.response.send_message(
            f"You hang up your tools as a {info['emoji']} **{info['name']}**. "
            "Your skill is remembered should you ever return."
        )

    @app_commands.command(name="work", description="Labour at your trade for goods and coin")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction):
        gid, uid = interaction.guild_id, interaction.user.id
        user = await self.db.get_user(gid, uid)
        if not user["job"]:
            await interaction.response.send_message(
                "You have no trade! Pick one with `/job choose` "
                "(see `/job list` for what the town offers).",
                ephemeral=True,
            )
            return

        job_key = user["job"]
        info = JOBS[job_key]
        skill = await self.db.get_skill(gid, uid, job_key)

        now = time.time()
        remaining = skill["last_work"] + info["cooldown"] - now
        if remaining > 0:
            await interaction.response.send_message(
                f"⏳ You are weary. Rest a while — you can work again "
                f"<t:{int(now + remaining)}:R>.",
                ephemeral=True,
            )
            return

        # Roll the yield
        tier = await self.db.get_tool_tier(gid, uid, job_key)
        multiplier = level_multiplier(skill["level"]) * tool_multiplier(tier)

        entries = info["yields"]
        item, lo, hi, _w = random.choices(
            entries, weights=[e[3] for e in entries], k=1
        )[0]
        qty = max(1, round(random.randint(lo, hi) * multiplier))
        tip = round(random.randint(*info["tip"]) * multiplier)
        xp_gain = random.randint(10, 18)

        level, xp, gained = apply_xp(skill["level"], skill["xp"], xp_gain)
        await self.db.update_skill(gid, uid, job_key, level, xp, now)
        await self.db.add_item(gid, uid, item, qty)
        await self.db.add_gold(gid, uid, tip)

        embed = discord.Embed(
            title=f"{info['emoji']} {info['name']} at work",
            description=random.choice(info["flavour"]),
            colour=discord.Colour.dark_gold(),
        )
        embed.add_field(
            name="Haul",
            value=f"{item_label(item)} × **{qty}**\nTip: **{fmt_gold(tip)}**",
            inline=True,
        )
        embed.add_field(name="Skill", value=f"+{xp_gain} XP", inline=True)
        if gained:
            embed.add_field(
                name="⭐ Level up!",
                value=f"Your {info['name']} skill is now level **{level}**!",
                inline=False,
            )
        embed.set_footer(
            text=f"Tool: {tool_name(job_key, tier)} · Sell your goods with /sell"
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="skills", description="View your skill levels in every trade")
    @app_commands.guild_only()
    @app_commands.describe(member="Whose skills to inspect (default: you)")
    async def skills(
        self, interaction: discord.Interaction, member: discord.Member | None = None
    ):
        target = member or interaction.user
        rows = await self.db.get_all_skills(interaction.guild_id, target.id)
        embed = discord.Embed(
            title=f"📖 Skills of {target.display_name}",
            colour=discord.Colour.dark_teal(),
        )
        if not rows:
            embed.description = "No trades practised yet. Start with `/job choose`!"
        for row in rows:
            info = JOBS.get(row["job"])
            if not info:
                continue
            needed = xp_needed(row["level"])
            embed.add_field(
                name=f"{info['emoji']} {info['name']} — Lv. {row['level']}",
                value=f"`{progress_bar(row['xp'], needed)}` {row['xp']}/{needed} XP",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Jobs(bot))
