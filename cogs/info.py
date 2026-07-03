"""Help and lore."""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from econ import formulas
from econ.buffs import active_buff_summary, active_buff_totals, apply_cooldown_buff
from econ.data.items import ITEMS
from econ.data.jobs import JOBS, MAX_JOB_UNLOCK_LEVEL
from econ.data.minigames import MINIGAMES
from econ.data.recipes import RECIPES
from ui.panels import NAME_W, Palette, Panel, chip

HELP_SECTIONS = [
    ("⚒️ Trade", ".job · .work · .skills"),
    ("🏪 Market", ".inventory · .market · .sell · .shop · .buy · .store"),
    ("🛠️ Crafting", ".recipes · .craft"),
    ("✨ Consumables", ".use · .buffs"),
    ("🗺️ Venture", ".venture"),
    ("💰 Gold", ".balance · .daily · .beg · .pay · .profile · .leaderboard"),
    ("🏦 Bank", ".bank · .deposit · .withdraw"),
    ("🗡️ Crime", ".pickpocket · .smuggle (both need Criminal, or lvl 5 in it)"),
    # Every job-specific minigame lives in this one section, not a new
    # section per job, however many of these exist.
    (
        "🎯 Job Minigames",
        ".harvest · .dig · .fish · .fell · .hunt · .bake · .tend · "
        ".stretch · .facet · .brew · .rob\n"
        "🟢 Easy · 🟡 Medium (lvl 15+) · 🔴 Hard (lvl 35+) -- pick a "
        "difficulty each time, harder pays much better",
    ),
    ("⏳ Cooldowns", ".cd · see every timer you're carrying, at a glance"),
]

# .pickpocket, .smuggle, and .rob all share the same "current Criminal,
# or Criminal skill level 5+" access rule as every other minigame.
CRIME_MIN_LEVEL_WITHOUT_JOB = formulas.MINIGAME_MIN_LEVEL_WITHOUT_JOB


class Info(commands.Cog):
    """Guidance for new townsfolk."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(name="help", description="A guide to life in the town")
    async def help(self, ctx: commands.Context):
        panel = Panel(timeout=None)
        panel.header("📜 Commands")
        for title, cmds in HELP_SECTIONS:
            panel.field(title, cmds)
        panel.footer("also work as /slash commands")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="about", description="About this humble town")
    async def about(self, ctx: commands.Context):
        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header("🏰 About the Town")
        panel.text(
            f"{len(JOBS)} trades · {len(ITEMS)} goods · {len(RECIPES)} recipes · "
            "daily-shifting market. No Discord roles, your rank is gold and "
            "skill alone. Walk an honest trade and build fame, or turn to "
            "crime and build infamy, but get caught robbing the bank and "
            "it's gone."
        )
        await ctx.send(view=panel)

    @commands.hybrid_command(
        name="cd", aliases=["cooldown", "cooldowns"],
        description="See every cooldown someone is currently carrying",
    )
    @commands.guild_only()
    @app_commands.describe(member="Whose cooldowns to check (default: you)")
    async def cooldowns(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        gid, uid = ctx.guild.id, target.id
        user = await self.db.get_user(gid, uid)
        skills = {s["job"]: s for s in await self.db.get_all_skills(gid, uid)}
        mg_last = await self.db.get_minigame_cooldowns(gid, uid)
        now = time.time()
        # Every cooldown below is read through the same buff totals the
        # actual commands apply (see econ/buffs.py), so the countdowns
        # shown here always match what running the command would do.
        buffs = await active_buff_totals(self.db, gid, uid)

        def status(ready_at: float) -> str:
            return "✅ ready now" if now >= ready_at else f"<t:{int(ready_at)}:R>"

        def skill_level(job_key: str) -> int:
            row = skills.get(job_key)
            return row["level"] if row else 0

        lines = []

        if user["job"]:
            job_info = JOBS[user["job"]]
            skill = skills.get(user["job"])
            level = skill["level"] if skill else 1
            last_work = skill["last_work"] if skill else 0
            cooldown = apply_cooldown_buff(
                formulas.effective_cooldown(job_info["cooldown"], level), buffs
            )
            lines.append(
                f"{job_info['emoji']} {chip(('.work', NAME_W))} {status(last_work + cooldown)}"
            )
        else:
            lines.append(f"⚒️ {chip(('.work', NAME_W))} *(take a trade with `.job` first)*")

        craft_skill = skills.get("crafting")
        craft_level = craft_skill["level"] if craft_skill else 1
        craft_last = craft_skill["last_work"] if craft_skill else 0
        craft_cooldown = apply_cooldown_buff(
            formulas.effective_cooldown(formulas.CRAFTING_COOLDOWN, craft_level), buffs
        )
        lines.append(
            f"🛠️ {chip(('.craft', NAME_W))} {status(craft_last + craft_cooldown)}"
        )

        lines.append(
            f"🪧 {chip(('.job choose', NAME_W))} "
            f"{status(user['last_job_switch'] + formulas.JOB_SWITCH_COOLDOWN)}"
        )
        lines.append(
            f"🗺️ {chip(('.venture', NAME_W))} "
            f"{status(user['last_venture'] + apply_cooldown_buff(formulas.VENTURE_COOLDOWN, buffs))}"
        )

        # Same UTC clock .daily itself uses.
        today = datetime.now(timezone.utc).date()
        if user["last_daily"] == today.isoformat():
            reset_at = datetime.combine(
                today + timedelta(days=1), dtime.min, tzinfo=timezone.utc
            )
            daily_status = f"<t:{int(reset_at.timestamp())}:R>"
        else:
            daily_status = "✅ ready now"
        lines.append(f"🕯️ {chip(('.daily', NAME_W))} {daily_status}")

        lines.append(
            f"🥺 {chip(('.beg', NAME_W))} "
            f"{status(mg_last.get('beg', 0.0) + apply_cooldown_buff(formulas.BEG_COOLDOWN, buffs))}"
        )

        crime_access = (
            user["job"] == "criminal"
            or skill_level("criminal") >= CRIME_MIN_LEVEL_WITHOUT_JOB
        )
        if crime_access:
            lines.append(
                f"🗡️ {chip(('.pickpocket', NAME_W))} "
                f"{status(user['last_pickpocket'] + apply_cooldown_buff(formulas.PICKPOCKET_COOLDOWN, buffs))}"
            )
            lines.append(
                f"🚚 {chip(('.smuggle', NAME_W))} "
                f"{status(mg_last.get('smuggle', 0.0) + apply_cooldown_buff(formulas.SMUGGLE_COOLDOWN, buffs))}"
            )
            lines.append(
                f"🏦 {chip(('.rob', NAME_W))} "
                f"{status(mg_last.get('criminal', 0.0) + apply_cooldown_buff(MINIGAMES['criminal']['cooldown'], buffs))}"
            )

        if user["job"] == "alchemist" or skill_level("alchemist") >= formulas.BREW_MIN_LEVEL_WITHOUT_JOB:
            lines.append(
                f"🧪 {chip(('.brew', NAME_W))} "
                f"{status(user['last_brew'] + apply_cooldown_buff(formulas.BREW_COOLDOWN, buffs))}"
            )

        for job_key, config in MINIGAMES.items():
            if job_key == "criminal":
                continue  # already shown above as .rob
            eligible = (
                user["job"] == job_key
                or skill_level(job_key) >= formulas.MINIGAME_MIN_LEVEL_WITHOUT_JOB
            )
            if not eligible:
                continue
            cooldown = apply_cooldown_buff(
                formulas.minigame_cooldown(
                    JOBS[job_key]["unlock_total_level"], MAX_JOB_UNLOCK_LEVEL
                ),
                buffs,
            )
            command_label = f".{config['command']}"
            lines.append(
                f"{JOBS[job_key]['emoji']} {chip((command_label, NAME_W))} "
                f"{status(mg_last.get(job_key, 0.0) + cooldown)}"
            )

        panel = Panel(timeout=None)
        panel.header(f"⏳ {target.display_name}'s Cooldowns")
        panel.text("\n".join(lines))
        buff_line = active_buff_summary(buffs)
        if buff_line:
            panel.footer(f"✨ active: {buff_line}")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
