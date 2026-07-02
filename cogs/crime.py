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
from econ.buffs import active_buff_summary, active_buff_totals, apply_cooldown_buff, apply_gold_buff
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

        buffs = await active_buff_totals(self.db, gid, uid)
        now = time.time()
        ready_at = attacker["last_pickpocket"] + apply_cooldown_buff(
            formulas.PICKPOCKET_COOLDOWN, buffs
        )
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
        new_rep = await self.db.add_reputation(gid, uid, -infamy_gain)
        new_infamy = formulas.reputation_infamy(new_rep)

        if success:
            # The gold buff sweetens the take, but never past what the
            # victim actually carries -- a buffed steal must not be able
            # to drive their pocket negative.
            delta = min(round(apply_gold_buff(delta, buffs)), target["gold"])
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
        footer = f"Purse: {purse:,} gold · 🗡️ +{infamy_gain} infamy ({new_infamy:,} total)"
        buff_line = active_buff_summary(buffs)
        if buff_line:
            footer += f"\n✨ active: {buff_line}"
        panel.footer(footer)
        await ctx.send(view=panel)

    @commands.hybrid_command(
        name="smuggle",
        description="Move contraband for a real payday, with a real chance of losing it",
    )
    @commands.guild_only()
    async def smuggle(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        is_criminal = user["job"] == "criminal"
        # Read-only: same phantom-row concern as .pickpocket.
        criminal_skill = await self.db.peek_skill(gid, uid, "criminal")
        if not is_criminal and criminal_skill["level"] < formulas.SMUGGLE_MIN_LEVEL_WITHOUT_JOB:
            await ctx.send(
                view=simple_panel(
                    "You are not a criminal, or high enough lvl "
                    f"({formulas.SMUGGLE_MIN_LEVEL_WITHOUT_JOB}) in it to "
                    "smuggle without being one.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        buffs = await active_buff_totals(self.db, gid, uid)
        now = time.time()
        last = await self.db.get_minigame_cooldown(gid, uid, "smuggle")
        ready_at = last + apply_cooldown_buff(formulas.SMUGGLE_COOLDOWN, buffs)
        if now < ready_at:
            await ctx.send(
                view=simple_panel(
                    f"🚚 Your contact isn't ready with another shipment yet. "
                    f"Ready <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        # The cooldown burns the moment the run starts, win or lose, so
        # walking away from a bad shipment can't reroll it.
        await self.db.set_minigame_cooldown(gid, uid, "smuggle", now)
        total = await self.db.total_level(gid, uid)
        infamy = formulas.reputation_infamy(user["reputation"])
        success, delta = formulas.roll_smuggle(criminal_skill["level"], infamy, total)

        if success:
            delta = round(apply_gold_buff(delta, buffs))
            await self.db.add_gold(gid, uid, delta)
            infamy_gain = random.randint(
                formulas.SMUGGLE_INFAMY_MIN, formulas.SMUGGLE_INFAMY_MAX
            )
            new_rep = await self.db.add_reputation(gid, uid, -infamy_gain)
            new_infamy = formulas.reputation_infamy(new_rep)
            await self.db.incr_stat(gid, uid, "smuggles_won")
            await self.db.incr_stat(gid, uid, "gold_from_smuggling", delta)
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header("🚚 Shipment Delivered")
            panel.text(f"The goods change hands quietly. You pocket **{delta:,} 🪙**.")
            footer_extra = f"🗡️ +{infamy_gain} infamy ({new_infamy:,} total)"
        else:
            fine = min(-delta, user["gold"])
            await self.db.add_gold(gid, uid, -fine)
            await self.db.incr_stat(gid, uid, "smuggles_lost")
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header("🚚 Shipment Seized")
            panel.text(
                f"A patrol stops your cart at the gate. The goods are gone, "
                f"and you pay a **{fine:,} 🪙** fine to walk away clean."
            )
            footer_extra = None

        purse = (await self.db.get_user(gid, uid))["gold"]
        footer = f"Purse: {purse:,} gold"
        if footer_extra:
            footer += f" · {footer_extra}"
        buff_line = active_buff_summary(buffs)
        if buff_line:
            footer += f"\n✨ active: {buff_line}"
        panel.footer(footer)
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Crime(bot))
