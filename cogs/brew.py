"""The Cauldron Brew: a memory minigame.

Watch a sequence of reagents flash by, then tap them back in order.
No risk of loss, reward scales with how many you recall correctly,
with a bonus for a flawless brew. Long cooldown, big single payout.

Access: current Alchemists can always brew, regardless of level.
Anyone else needs Alchemist skill level 5+ (persists across job
switches, so once earned it's never lost).
"""

from __future__ import annotations

import asyncio
import random
import time

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import formulas
from ui.panels import AMT_W, NAME_W, Palette, Panel, chip, simple_panel

REAGENTS = {
    "herb": "🌿", "water": "💧", "fire": "🔥", "flask": "⚗️",
    "spark": "✨", "shroom": "🍄", "venom": "💀",
}
REAGENT_KEYS = list(REAGENTS)
REVEAL_DELAY = 1.1     # seconds between flashing each reagent
ANSWER_TIMEOUT = 20    # seconds to tap each reagent before the view expires


class BrewSession:
    """One player's in-progress cauldron attempt: holds the target
    sequence and how far they've correctly recalled it so far."""

    def __init__(
        self, db, gid: int, uid: int, level: int, xp: int, last_work: float,
        *, dry_run: bool = False,
    ):
        self.db = db
        self.gid = gid
        self.uid = uid
        self.level = level
        self.xp = xp
        self.last_work = last_work
        self.dry_run = dry_run
        self.length = formulas.brew_sequence_length(level)
        self.sequence = [random.choice(REAGENT_KEYS) for _ in range(self.length)]
        self.progress = 0
        self.done = False

    def answer_panel(self) -> Panel:
        dots = "🟢" * self.progress + "⚪" * (self.length - self.progress)
        panel = Panel(accent=Palette.GOLD, author_id=self.uid, timeout=ANSWER_TIMEOUT)
        panel.header("🧪 Repeat the Sequence!")
        panel.text(f"`{dots}`  ({self.progress}/{self.length})")
        buttons = []
        for key in REAGENT_KEYS:
            btn = ui.Button(emoji=REAGENTS[key], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_handler(key)
            buttons.append(btn)
        # Discord caps an ActionRow at 5 components; split across rows.
        for i in range(0, len(buttons), 5):
            panel.buttons(*buttons[i : i + 5])
        deadline = int(time.time()) + ANSWER_TIMEOUT
        panel.footer(f"⏱️ answer by <t:{deadline}:R>")
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
        if not self.dry_run:
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

        reward_line = (
            f"💰 {chip(('Reward', NAME_W), (f'{reward:,}', -AMT_W))} 🪙"
            if reward else "💰 No gold this time."
        )
        panel.text(reward_line)

        footer = f"{self.progress}/{self.length} recalled correctly"
        if xp_gain:
            footer += f" · +{xp_gain} XP"
        if levels_gained and not self.dry_run:
            footer += f" · ⭐ now level {new_level}"
        if self.dry_run:
            footer = "🧪 TEST MODE, nothing was actually awarded · " + footer
        panel.footer(footer)
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
        description="Test your memory at the cauldron for a big payout",
    )
    @commands.guild_only()
    async def brew(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        is_alchemist = user["job"] == "alchemist"
        # Read-only: peeking must never create a phantom alchemist skill
        # row for a player who was never one (that would silently inflate
        # their total skill level, the same bug .job info had before).
        alchemist_skill = await self.db.peek_skill(gid, uid, "alchemist")
        if not is_alchemist and alchemist_skill["level"] < formulas.BREW_MIN_LEVEL_WITHOUT_JOB:
            await ctx.send(
                view=simple_panel(
                    "You are not an alchemist, or high enough lvl "
                    f"({formulas.BREW_MIN_LEVEL_WITHOUT_JOB}) to do brewery "
                    "without being an alchemist.",
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
        await self._run_brew(ctx, session)

    @commands.hybrid_command(
        name="brewtest",
        description="[Admin] Try the cauldron minigame without a job, cooldown, or real rewards",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Alchemist level to simulate (default: 1)")
    async def brewtest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        session = BrewSession(
            self.db, ctx.guild.id, ctx.author.id, level, 0, 0, dry_run=True
        )
        await self._run_brew(ctx, session, test_mode=True)

    async def _run_brew(
        self, ctx: commands.Context, session: BrewSession, *, test_mode: bool = False
    ) -> None:
        """Shared reveal-then-answer flow for both .brew and .brewtest."""
        panel = Panel(accent=Palette.PURPLE, timeout=None)
        panel.header("🧪 The Cauldron Brew")
        if test_mode:
            panel.text("🧪 *TEST MODE, no job, cooldown, or rewards apply.*")
        panel.text(f"Sequence length: **{session.length}** reagents")
        panel.footer("👀 watch closely, and remember the order")
        message = await ctx.send(view=panel)

        for revealed in range(1, session.length + 1):
            await asyncio.sleep(REVEAL_DELAY)
            reagent = session.sequence[revealed - 1]
            flash = Panel(accent=Palette.PURPLE, timeout=None)
            flash.header("🧪 The Cauldron Brew")
            flash.text(f"Reagent {revealed}/{session.length}")
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
