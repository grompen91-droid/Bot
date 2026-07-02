"""The Cauldron Brew: an Alchemist-only memory minigame.

Watch a sequence of reagents flash by, then tap them back in order.
No risk of loss, reward scales with how many you recall correctly,
with a bonus for a flawless brew. Long cooldown, big single payout,
the endgame Alchemist's signature activity.
"""

from __future__ import annotations

import asyncio
import random
import time

import discord
from discord import ui
from discord.ext import commands

from econ import formulas
from ui.panels import Palette, Panel, simple_panel

REAGENTS = {
    "herb": "🌿", "water": "💧", "fire": "🔥", "flask": "⚗️",
    "spark": "✨", "shroom": "🍄", "venom": "💀",
}
REAGENT_KEYS = list(REAGENTS)
REVEAL_DELAY = 1.1  # seconds between flashing each reagent


class BrewSession:
    """One player's in-progress cauldron attempt: holds the target
    sequence and how far they've correctly recalled it so far."""

    def __init__(
        self, db, gid: int, uid: int, level: int, xp: int, last_work: float,
    ):
        self.db = db
        self.gid = gid
        self.uid = uid
        self.level = level
        self.xp = xp
        self.last_work = last_work
        self.length = formulas.brew_sequence_length(level)
        self.sequence = [random.choice(REAGENT_KEYS) for _ in range(self.length)]
        self.progress = 0
        self.done = False

    def answer_panel(self) -> Panel:
        dots = "🟢" * self.progress + "⚪" * (self.length - self.progress)
        panel = Panel(accent=Palette.GOLD, author_id=self.uid, timeout=30)
        panel.header("🧪 Repeat the Sequence!")
        panel.text(f"`{dots}`")
        buttons = []
        for key in REAGENT_KEYS:
            btn = ui.Button(emoji=REAGENTS[key], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_handler(key)
            buttons.append(btn)
        # Discord caps an ActionRow at 5 components; split across rows.
        for i in range(0, len(buttons), 5):
            panel.buttons(*buttons[i : i + 5])
        return panel

    def _make_handler(self, key: str):
        async def handler(interaction: discord.Interaction) -> None:
            await self.on_tap(interaction, key)
        return handler

    async def on_tap(self, interaction: discord.Interaction, key: str) -> None:
        if self.done:
            await interaction.response.defer()
            return
        expected = self.sequence[self.progress]
        if key != expected:
            self.done = True
            await self._finish(
                interaction, success=False, wrong_key=key, expected_key=expected
            )
            return
        self.progress += 1
        if self.progress == self.length:
            self.done = True
            await self._finish(interaction, success=True)
        else:
            await interaction.response.edit_message(view=self.answer_panel())

    async def _finish(
        self,
        interaction: discord.Interaction,
        *,
        success: bool,
        wrong_key: str | None = None,
        expected_key: str | None = None,
    ) -> None:
        total = await self.db.total_level(self.gid, self.uid)
        reward, perfect = formulas.roll_brew_reward(self.progress, self.length, total)
        xp_gain = self.progress * formulas.BREW_XP_PER_SYMBOL

        new_level, new_xp, levels_gained = formulas.apply_xp(
            self.level, self.xp, xp_gain
        )
        await self.db.update_skill(
            self.gid, self.uid, "alchemist", new_level, new_xp, self.last_work
        )
        if reward:
            await self.db.add_gold(self.gid, self.uid, reward)
        await self.db.incr_stat(self.gid, self.uid, "brews_completed")
        if perfect:
            await self.db.incr_stat(self.gid, self.uid, "brews_perfect")
        if reward:
            await self.db.incr_stat(self.gid, self.uid, "gold_from_brewing", reward)

        panel = Panel(accent=Palette.GREEN if success else Palette.RED, timeout=None)
        if success:
            panel.header("🧪 A Flawless Brew!" if perfect else "🧪 Brew Complete")
            panel.text(
                "*Every reagent, in perfect order. The cauldron glows gold.*"
                if perfect else
                "*You recall the sequence and the potion sets true.*"
            )
        else:
            panel.header("🧪 The Brew Spoils")
            panel.text(
                f"*You reach for {REAGENTS[wrong_key]}, but the recipe called "
                f"for {REAGENTS[expected_key]}. The mixture curdles.*"
            )
        lines = [f"💰 **{reward:,} 🪙**" if reward else "💰 No gold this time."]
        if xp_gain:
            lines.append(f"+{xp_gain} XP")
        if levels_gained:
            lines.append(f"⭐ Alchemist is now level **{new_level}**!")
        panel.text("\n".join(lines))
        panel.footer(f"{self.progress}/{self.length} recalled correctly")
        await interaction.response.edit_message(view=panel)


class Brew(commands.Cog):
    """Alchemy: a memory of reagents, not chance."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(
        name="brew",
        description="Test your memory at the cauldron for a big payout (Alchemist only)",
    )
    @commands.guild_only()
    async def brew(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        if user["job"] != "alchemist":
            await ctx.send(
                view=simple_panel(
                    "🧪 Only an Alchemist knows the cauldron's secrets. Take "
                    "up the trade with `.job choose alchemist`.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        now = time.time()
        ready_at = user["last_brew"] + formulas.BREW_COOLDOWN
        if now < ready_at:
            await ctx.send(
                view=simple_panel(
                    f"🧪 The cauldron is still cooling. Ready <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        # The cooldown burns the moment the brew starts, win or lose, so
        # walking away mid-brew can't be used to reroll a bad sequence.
        await self.db.set_last_brew(gid, uid, now)

        skill = await self.db.get_skill(gid, uid, "alchemist")
        session = BrewSession(
            self.db, gid, uid, skill["level"], skill["xp"], skill["last_work"]
        )

        panel = Panel(accent=Palette.PURPLE, timeout=None)
        panel.header("🧪 The Cauldron Brew")
        panel.text("👀 *Watch closely, and remember the order...*")
        message = await ctx.send(view=panel)

        for reagent in session.sequence:
            await asyncio.sleep(REVEAL_DELAY)
            flash = Panel(accent=Palette.PURPLE, timeout=None)
            flash.header("🧪 The Cauldron Brew")
            flash.text(f"# {REAGENTS[reagent]}")
            try:
                await message.edit(view=flash)
            except discord.HTTPException:
                return
        await asyncio.sleep(REVEAL_DELAY)

        answer_panel = session.answer_panel()
        answer_panel.message = message
        await message.edit(view=answer_panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Brew(bot))
