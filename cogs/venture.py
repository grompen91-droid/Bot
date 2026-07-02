"""Ventures: a job-independent, long-cooldown risk/reward minigame.

Pick one of three routes with different odds. It's a genuine choice,
not a random roll on command, and the payout scales with town rank and
an on-going win streak, so it stays worth returning to at any level.
"""

from __future__ import annotations

import random
import time

import discord
from discord import ui
from discord.ext import commands

from econ import formulas
from econ.data.ventures import VENTURE_PATHS
from ui.panels import AMT_W, NAME_W, Palette, Panel, chip, simple_panel


class Venture(commands.Cog):
    """Beyond the town walls."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(
        name="venture", aliases=["adventure"],
        description="Risk a journey beyond the town walls for gold",
    )
    @commands.guild_only()
    async def venture(self, ctx: commands.Context):
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        now = time.time()
        ready_at = user["last_venture"] + formulas.VENTURE_COOLDOWN
        if now < ready_at:
            await ctx.send(
                view=simple_panel(
                    "🗺️ Your legs still ache from the last venture. "
                    f"You can set out again <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        total = await self.db.total_level(ctx.guild.id, ctx.author.id)
        streak = user["venture_streak"]
        mult = formulas.venture_multiplier(total, streak)

        panel = Panel(accent=Palette.GOLD, author_id=ctx.author.id, timeout=120)
        panel.header("🗺️ Beyond the Town Walls")
        panel.text(
            "A courier has posted three routes on the board. Choose your "
            "path: the deeper you go, the more you risk, and the more "
            "you stand to gain."
        )
        panel.divider()
        blocks = []
        for path in VENTURE_PATHS.values():
            lo, hi = path["reward"]
            range_s = f"{round(lo * mult):,}-{round(hi * mult):,}"
            win_s = f"win {path['success']:.0%}"
            blocks.append(
                f"{path['emoji']} **{path['name']}** · {path['risk']}\n"
                f"{chip((win_s, 8), (range_s, -12))} 🪙"
            )
        panel.text("\n\n".join(blocks))

        footer = f"×{mult:.2f} bonus from total skill level"
        if streak:
            footer += f" & 🔥 {streak} win streak"
        panel.footer(footer)

        buttons = []
        for key, path in VENTURE_PATHS.items():
            btn = ui.Button(
                label=path["name"], emoji=path["emoji"],
                style=discord.ButtonStyle.secondary,
            )
            btn.callback = self._make_resolver(key)
            buttons.append(btn)
        panel.buttons(*buttons)
        panel.message = await ctx.send(view=panel)

    def _make_resolver(self, path_key: str):
        async def resolver(interaction: discord.Interaction) -> None:
            await self._resolve(interaction, path_key)

        return resolver

    async def _resolve(self, interaction: discord.Interaction, path_key: str) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        user = await self.db.get_user(gid, uid)
        now = time.time()
        ready_at = user["last_venture"] + formulas.VENTURE_COOLDOWN
        if now < ready_at:
            await interaction.response.send_message(
                view=simple_panel(
                    f"🗺️ Too soon, try again <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        total = await self.db.total_level(gid, uid)
        streak = user["venture_streak"]
        path = VENTURE_PATHS[path_key]
        success, delta = formulas.roll_venture(path, total, streak)

        new_streak = streak + 1 if success else 0
        await self.db.set_venture(gid, uid, now, new_streak)
        balance = await self.db.add_gold(gid, uid, delta)
        await self.db.incr_stat(gid, uid, "ventures_won" if success else "ventures_lost")
        if success:
            await self.db.incr_stat(gid, uid, "gold_from_ventures", delta)

        panel = Panel(accent=Palette.GREEN if success else Palette.RED, timeout=None)
        panel.header(f"{path['emoji']} {path['name']}")
        if success:
            panel.text(f"✅ *{random.choice(path['success_flavour'])}*")
            panel.text(
                f"💰 {chip(('Gained', NAME_W), (f'{delta:,}', -AMT_W))} 🪙"
            )
        else:
            panel.text(f"❌ *{random.choice(path['fail_flavour'])}*")
            if delta:
                panel.text(
                    f"💸 {chip(('Lost', NAME_W), (f'{-delta:,}', -AMT_W))} 🪙"
                )
        footer = f"Purse: {balance:,} gold"
        if success and new_streak > 1:
            footer += f" · 🔥 {new_streak} win streak"
        elif not success and streak:
            footer += " · streak reset"
        ready = int(now + formulas.VENTURE_COOLDOWN)
        footer += f"\nnext venture <t:{ready}:R>"
        panel.footer(footer)
        await interaction.response.edit_message(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Venture(bot))
