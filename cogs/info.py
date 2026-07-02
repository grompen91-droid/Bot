"""Help and lore."""

from __future__ import annotations

from discord.ext import commands

from econ import formulas
from econ.data.items import ITEMS
from econ.data.jobs import JOBS
from ui.panels import Palette, Panel

HELP_SECTIONS = [
    (
        "⚒️ Your Trade",
        [
            ("`.job`", "the job board — pick a trade from the menu"),
            ("`.job choose <trade>`", "take up a trade by name"),
            ("`.job info <trade>`", "yields, odds, and your standing"),
            ("`.job quit`", "hang up your tools (skills are kept)"),
            ("`.work`", "labour for goods, coin, and XP"),
            ("`.skills [member]`", "skill levels in every trade"),
        ],
    ),
    (
        "🏪 The Market",
        [
            ("`.inventory`", "your satchel and what it's worth today"),
            ("`.market`", "today's prices — they drift every day"),
            ("`.sell [item] [amount]`", "sell goods (no item = sell everything)"),
            ("`.shop`", "the smithy: tool tiers for your trade"),
            ("`.buy`", "buy the next tool tier"),
        ],
    ),
    (
        "💰 Gold",
        [
            ("`.balance [member]`", "count the coin in a purse"),
            ("`.daily`", "daily stipend — streaks and skill pay more"),
            ("`.pay <member> <amount>`", "hand coin to another townsfolk"),
            ("`.profile [member]`", "your standing in the town"),
            ("`.leaderboard [gold|skills]`", "the town's finest"),
        ],
    ),
]


class Info(commands.Cog):
    """Guidance for new townsfolk."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="help", description="A guide to life in the town")
    async def help(self, ctx: commands.Context):
        panel = Panel(timeout=None)
        panel.header("📜 A Guide to Life in the Town")
        panel.text(
            "Take a trade, `.work` it to gather goods, `.sell` them at the "
            "market, and save for better tools at the `.shop`. Skill in each "
            "trade grows forever — even if you switch.\n"
            "*Every command also works as a slash command.*"
        )
        for title, entries in HELP_SECTIONS:
            panel.divider()
            panel.field(
                title,
                "\n".join(f"{cmd} — {desc}" for cmd, desc in entries),
            )
        panel.footer("higher skill: bigger hauls, faster work, luckier finds, fatter tips")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="about", description="About this humble town")
    async def about(self, ctx: commands.Context):
        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header("🏰 About the Town")
        panel.text(
            f"A medieval economy for this server: **{len(JOBS)}** trades, "
            f"**{len(ITEMS)}** goods, **{len(formulas.TOOL_MULTIPLIERS) - 1}** "
            "tool tiers per trade, and a market that shifts every day.\n\n"
            "No Discord roles are used — your rank in town is measured in "
            "gold and skill alone."
        )
        panel.footer("start with .help")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
