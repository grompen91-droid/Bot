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
            ("`.job`", "the job board, pick a trade"),
            ("`.job info <trade>`", "yields, odds, your standing"),
            ("`.job quit`", "quit (skills are kept)"),
            ("`.work`", "labour for goods, coin, and XP"),
            ("`.skills`", "skill levels in every trade"),
        ],
    ),
    (
        "🏪 The Market",
        [
            ("`.inventory`", "your satchel and its worth"),
            ("`.market`", "today's prices"),
            ("`.sell [item] [amount]`", "sell goods (nothing = sell all)"),
            ("`.shop` / `.buy`", "the smithy, better tools"),
        ],
    ),
    (
        "💰 Gold",
        [
            ("`.balance`", "coin in your purse"),
            ("`.daily`", "daily stipend, streaks pay more"),
            ("`.pay <member> <amount>`", "hand coin to someone"),
            ("`.profile`", "your standing in the town"),
            ("`.leaderboard`", "the town's finest"),
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
            "Take a trade, `.work` to gather goods, `.sell` them, "
            "save for better tools at the `.shop`."
        )
        for title, entries in HELP_SECTIONS:
            panel.divider()
            panel.field(
                title,
                "\n".join(f"{cmd} · {desc}" for cmd, desc in entries),
            )
        panel.footer("every command also works as a slash command")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="about", description="About this humble town")
    async def about(self, ctx: commands.Context):
        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header("🏰 About the Town")
        panel.text(
            f"A medieval economy for this server: **{len(JOBS)}** trades, "
            f"**{len(ITEMS)}** goods, **{len(formulas.TOOL_MULTIPLIERS) - 1}** "
            "tool tiers per trade, and a market that shifts every day.\n\n"
            "No Discord roles are used. Your rank in town is measured in "
            "gold and skill alone."
        )
        panel.footer("start with .help")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
