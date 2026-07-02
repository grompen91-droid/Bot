"""Help and lore."""

from __future__ import annotations

from discord.ext import commands

from econ import formulas
from econ.data.items import ITEMS
from econ.data.jobs import JOBS
from ui.panels import Palette, Panel

HELP_SECTIONS = [
    ("⚒️ Trade", ".job · .work · .skills"),
    ("🏪 Market", ".inventory · .market · .sell · .shop · .buy"),
    ("🗺️ Venture", ".venture"),
    ("💰 Gold", ".balance · .daily · .pay · .profile · .leaderboard"),
    ("🏦 Bank", ".bank · .deposit · .withdraw"),
    ("🗡️ Crime", ".pickpocket"),
    # Every job-specific minigame lives in this one section, not a new
    # section per job, however many of these exist.
    (
        "🎯 Job Minigames",
        ".harvest · .dig · .fish · .fell · .hunt · .bake · .tend · .brew",
    ),
]


class Info(commands.Cog):
    """Guidance for new townsfolk."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
            f"{len(JOBS)} trades · {len(ITEMS)} goods · daily-shifting market. "
            "No Discord roles, your rank is gold and skill alone."
        )
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
