"""Help and lore."""

from __future__ import annotations

import time
from datetime import date, datetime, time as dtime, timedelta

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
    ("🏪 Market", ".inventory · .market · .sell · .shop · .buy"),
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
        ".harvest · .dig · .fish · .fell · .hunt · .bake · .tend · .brew · .rob",
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
        description="See every cooldown you're currently carrying",
    )
    @commands.guild_only()
    async def cooldowns(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        skills = {s["job"]: s for s in await self.db.get_all_skills(gid, uid)}
        now = time.time()
        # .work/.craft are the only two that already respect active
        # buffs (see econ/buffs.py); every other command below still
        # ignores them, so showing the buffed number for those would be
        # a lie about what will actually happen when you run them.
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
            f"{status(user['last_venture'] + formulas.VENTURE_COOLDOWN)}"
        )

        today = date.today()
        if user["last_daily"] == today.isoformat():
            reset_at = datetime.combine(today + timedelta(days=1), dtime.min)
            daily_status = f"<t:{int(reset_at.timestamp())}:R>"
        else:
            daily_status = "✅ ready now"
        lines.append(f"🕯️ {chip(('.daily', NAME_W))} {daily_status}")

        beg_last = await self.db.get_minigame_cooldown(gid, uid, "beg")
        lines.append(
            f"🥺 {chip(('.beg', NAME_W))} {status(beg_last + formulas.BEG_COOLDOWN)}"
        )

        crime_access = (
            user["job"] == "criminal"
            or skill_level("criminal") >= CRIME_MIN_LEVEL_WITHOUT_JOB
        )
        if crime_access:
            lines.append(
                f"🗡️ {chip(('.pickpocket', NAME_W))} "
                f"{status(user['last_pickpocket'] + formulas.PICKPOCKET_COOLDOWN)}"
            )
            smuggle_last = await self.db.get_minigame_cooldown(gid, uid, "smuggle")
            lines.append(
                f"🚚 {chip(('.smuggle', NAME_W))} "
                f"{status(smuggle_last + formulas.SMUGGLE_COOLDOWN)}"
            )
            rob_last = await self.db.get_minigame_cooldown(gid, uid, "criminal")
            lines.append(
                f"🏦 {chip(('.rob', NAME_W))} "
                f"{status(rob_last + MINIGAMES['criminal']['cooldown'])}"
            )

        if user["job"] == "alchemist" or skill_level("alchemist") >= formulas.BREW_MIN_LEVEL_WITHOUT_JOB:
            lines.append(
                f"🧪 {chip(('.brew', NAME_W))} "
                f"{status(user['last_brew'] + formulas.BREW_COOLDOWN)}"
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
            cooldown = formulas.minigame_cooldown(
                JOBS[job_key]["unlock_total_level"], MAX_JOB_UNLOCK_LEVEL
            )
            last = await self.db.get_minigame_cooldown(gid, uid, job_key)
            command_label = f".{config['command']}"
            lines.append(
                f"{JOBS[job_key]['emoji']} {chip((command_label, NAME_W))} "
                f"{status(last + cooldown)}"
            )

        panel = Panel(timeout=None)
        panel.header(f"⏳ {ctx.author.display_name}'s Cooldowns")
        panel.text("\n".join(lines))
        buff_line = active_buff_summary(buffs)
        if buff_line:
            panel.footer(f"✨ active: {buff_line} (already reflected in .work/.craft above)")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
