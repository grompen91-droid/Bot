"""Crime: pickpocketing other townsfolk. Banked gold is always safe;
only what's sitting loose in a pocket can be stolen.

Access follows the same rule as .brew and the per-job minigames:
current Criminals can always pickpocket, or anyone with Criminal
skill level 5+ (persists across job switches). Odds and steal size
both scale with that same skill level, and every attempt, win or
lose, builds a little infamy.
"""

from __future__ import annotations

import random
import time

import discord
from discord import app_commands
from discord.ext import commands

from econ import formulas
from ui.panels import Palette, Panel, simple_panel


class Crime(commands.Cog):
    """The seedier side of town."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(
        name="pickpocket", aliases=["steal", "pp"],
        description="Try to lift coin from another townsfolk's pocket",
    )
    @commands.guild_only()
    @app_commands.describe(member="Who to target")
    async def pickpocket(self, ctx: commands.Context, member: discord.Member):
        if member.bot or member.id == ctx.author.id:
            await ctx.send(
                view=simple_panel(
                    "You can't pickpocket yourself, nor a construct of gears "
                    "and magic.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        gid, uid = ctx.guild.id, ctx.author.id
        attacker = await self.db.get_user(gid, uid)
        is_criminal = attacker["job"] == "criminal"
        # Read-only: peeking must never create a phantom criminal skill
        # row for a player who was never one (that would silently inflate
        # their total skill level, the same bug .job info had before).
        criminal_skill = await self.db.peek_skill(gid, uid, "criminal")
        if not is_criminal and criminal_skill["level"] < formulas.PICKPOCKET_MIN_LEVEL_WITHOUT_JOB:
            await ctx.send(
                view=simple_panel(
                    "You are not a criminal, or high enough lvl "
                    f"({formulas.PICKPOCKET_MIN_LEVEL_WITHOUT_JOB}) in it to "
                    "pickpocket without being one.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        now = time.time()
        ready_at = attacker["last_pickpocket"] + formulas.PICKPOCKET_COOLDOWN
        if now < ready_at:
            await ctx.send(
                view=simple_panel(
                    f"🗡️ Lie low a while longer. Ready <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        target = await self.db.get_user(gid, member.id)
        if now < target["robbed_until"]:
            await ctx.send(
                view=simple_panel(
                    f"🛡️ {member.display_name} is watching their purse closely "
                    f"after being robbed recently. Try again "
                    f"<t:{int(target['robbed_until'])}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        if target["gold"] < formulas.PICKPOCKET_MIN_TARGET_POCKET:
            await ctx.send(
                view=simple_panel(
                    f"{member.display_name}'s pockets aren't worth the risk.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        success, delta = formulas.roll_pickpocket(target["gold"], criminal_skill["level"])
        await self.db.set_last_pickpocket(gid, uid, now)
        infamy_gain = random.randint(
            formulas.PICKPOCKET_INFAMY_MIN, formulas.PICKPOCKET_INFAMY_MAX
        )
        new_infamy = await self.db.add_infamy(gid, uid, infamy_gain)

        if success:
            await self.db.add_gold(gid, member.id, -delta)
            await self.db.add_gold(gid, uid, delta)
            await self.db.set_robbed_until(
                gid, member.id, now + formulas.PICKPOCKET_VICTIM_SHIELD
            )
            await self.db.incr_stat(gid, uid, "pickpockets_won")
            await self.db.incr_stat(gid, uid, "gold_from_pickpocketing", delta)
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header("🗡️ Clean Getaway")
            panel.text(
                f"You lift **{delta:,} 🪙** from {member.display_name}'s "
                "pocket and vanish into the crowd."
            )
        else:
            fine = min(-delta, attacker["gold"])
            await self.db.add_gold(gid, uid, -fine)
            await self.db.incr_stat(gid, uid, "pickpockets_lost")
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header("🗡️ Caught Red-Handed!")
            panel.text(
                f"{member.display_name} notices your hand and shouts! You "
                f"pay a **{fine:,} 🪙** fine fleeing the scene."
            )

        purse = (await self.db.get_user(gid, uid))["gold"]
        panel.footer(
            f"Purse: {purse:,} gold · 🗡️ +{infamy_gain} infamy ({new_infamy:,} total)"
        )
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Crime(bot))
