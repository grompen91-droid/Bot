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
from econ.buffs import (
    active_buff_summary,
    active_buff_totals,
    apply_cooldown_buff,
    apply_gold_buff,
    apply_xp_buff,
)
from econ.data.consumables import BREW_POTION_CHANCE, BREW_POTIONS
from econ.data.items import ITEMS
from econ.data.jobs import JOBS, MAX_JOB_UNLOCK_LEVEL
from ui.panels import (
    AMT_W,
    NAME_W,
    InteractionSender,
    Palette,
    Panel,
    RoundPanel,
    chip,
    simple_panel,
)

REAGENTS = {
    "herb": "🌿", "water": "💧", "fire": "🔥", "flask": "⚗️",
    "spark": "✨", "shroom": "🍄", "venom": "💀",
}
REAGENT_KEYS = list(REAGENTS)
REVEAL_DELAY = 1.1     # seconds between flashing each reagent, at Easy
ANSWER_TIMEOUT = 20    # seconds to tap each reagent before the view expires, at Easy


class BrewSession:
    """One player's in-progress cauldron attempt: holds the target
    sequence and how far they've correctly recalled it so far.

    `difficulty` ("easy"/"medium"/"hard", see formulas.DIFFICULTIES) is
    chosen up front by .brew's difficulty picker: it fixes the
    sequence length and tightens both the reveal pace and the answer
    timeout, same shape as every other per-job minigame."""

    def __init__(
        self, db, gid: int, uid: int, level: int, xp: int, last_work: float,
        *, dry_run: bool = False, buffs: dict | None = None, difficulty: str = "easy",
    ):
        self.db = db
        self.gid = gid
        self.uid = uid
        self.level = level
        self.xp = xp
        self.last_work = last_work
        self.dry_run = dry_run
        self.buffs = buffs or {}
        self.difficulty = difficulty
        self.tier = formulas.DIFFICULTIES[difficulty]
        self.length = formulas.brew_sequence_length(difficulty)
        self.reveal_delay = max(0.4, REVEAL_DELAY * self.tier["timeout_mult"])
        self.answer_timeout = max(4, round(ANSWER_TIMEOUT * self.tier["timeout_mult"]))
        self.sequence = [random.choice(REAGENT_KEYS) for _ in range(self.length)]
        self.progress = 0
        self.done = False
        self.current_panel: RoundPanel | None = None

    def answer_panel(self) -> Panel:
        dots = "🟢" * self.progress + "⚪" * (self.length - self.progress)
        panel = RoundPanel(
            self, accent=Palette.GOLD, author_id=self.uid, timeout=self.answer_timeout
        )
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
        deadline = int(time.time()) + self.answer_timeout
        panel.footer(f"⏱️ answer by <t:{deadline}:R>")
        self.current_panel = panel
        return panel

    def _make_handler(self, key: str):
        async def handler(interaction: discord.Interaction) -> None:
            await self.on_tap(interaction, key)
        return handler

    async def on_tap(self, interaction: discord.Interaction, key: str) -> None:
        if self.done:
            await interaction.response.defer()
            return
        # Discord.py refreshes a view's own timeout on every tap, so the
        # view this button belongs to must be stopped explicitly here or
        # its now-stale background timer can fire later and wrongly
        # resolve a later round as a timeout, well after this one ended.
        if self.current_panel is not None:
            self.current_panel.stop()
        expected = self.sequence[self.progress]
        if key != expected:
            self.done = True
            panel = await self._result_panel(
                success=False, wrong_key=key, expected_key=expected
            )
            await interaction.response.edit_message(view=panel)
            return
        self.progress += 1
        if self.progress == self.length:
            self.done = True
            panel = await self._result_panel(success=True)
            await interaction.response.edit_message(view=panel)
        else:
            next_panel = self.answer_panel()
            next_panel.message = interaction.message
            await interaction.response.edit_message(view=next_panel)

    async def on_round_timeout(self, message: discord.Message) -> None:
        if self.done:
            return
        self.done = True
        panel = await self._result_panel(success=False, timed_out=True)
        try:
            await message.edit(view=panel)
        except discord.HTTPException:
            pass

    async def _result_panel(
        self,
        *,
        success: bool,
        wrong_key: str | None = None,
        expected_key: str | None = None,
        timed_out: bool = False,
    ) -> Panel:
        total = await self.db.total_level(self.gid, self.uid)
        user = await self.db.get_user(self.gid, self.uid)
        fame_mult = formulas.fame_multiplier(formulas.reputation_fame(user["reputation"]))
        reward, perfect = formulas.roll_brew_reward(
            self.progress, self.length, self.level, total,
            JOBS["alchemist"]["unlock_total_level"], MAX_JOB_UNLOCK_LEVEL,
            extra_multiplier=fame_mult * self.tier["reward_mult"],
        )
        reward = round(apply_gold_buff(reward, self.buffs))
        xp_gain = round(apply_xp_buff(self.progress * formulas.BREW_XP_PER_SYMBOL, self.buffs))

        new_level, new_xp, levels_gained = formulas.apply_xp(
            self.level, self.xp, xp_gain
        )
        fame_gained = 0
        potion = None
        if success and (perfect or random.random() < BREW_POTION_CHANCE):
            potion = random.choice(BREW_POTIONS)
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
            if success:
                await self.db.add_reputation(self.gid, self.uid, formulas.MINIGAME_FAME_ON_SUCCESS)
                fame_gained = formulas.MINIGAME_FAME_ON_SUCCESS
            if potion:
                await self.db.add_item(self.gid, self.uid, potion, 1)

        panel = Panel(accent=Palette.GREEN if success else Palette.RED, timeout=None)
        if success:
            panel.header("🧪 A Flawless Brew!" if perfect else "🧪 Brew Complete")
            panel.text(
                "*Every reagent, in perfect order. The cauldron glows gold.*"
                if perfect else
                "*You recall the sequence and the potion sets true.*"
            )
        elif timed_out:
            panel.header("🧪 The Brew Spoils")
            panel.text("*You hesitate too long over the cauldron, and the brew spoils.*")
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

        if potion:
            potion_info = ITEMS[potion]
            panel.text(
                f"🧪 The cauldron also yields a **{potion_info['emoji']} {potion_info['name']}**! "
                f"*(usable with `.use`)*"
            )

        footer = f"{self.tier['emoji']} {self.tier['label']} · {self.progress}/{self.length} recalled correctly"
        if xp_gain:
            footer += f" · +{xp_gain} XP"
        if levels_gained and not self.dry_run:
            footer += f" · ⭐ now level {new_level}"
        if fame_gained:
            footer += f" · 🌟 +{fame_gained} fame"
        buff_line = active_buff_summary(self.buffs)
        if buff_line:
            footer += f"\n✨ active: {buff_line}"
        if self.dry_run:
            footer = "🧪 TEST MODE, nothing was actually awarded · " + footer
        panel.footer(footer)
        return panel


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

        buffs = await active_buff_totals(self.db, gid, uid)
        now = time.time()
        ready_at = user["last_brew"] + apply_cooldown_buff(formulas.BREW_COOLDOWN, buffs)
        if now < ready_at:
            await ctx.send(
                view=simple_panel(
                    f"🧪 The cauldron is still cooling. Ready <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        # Cooldown isn't burned until a difficulty is actually picked --
        # declining, or just looking, shouldn't cost the attempt.
        skill = await self.db.get_skill(gid, uid, "alchemist")
        await self._send_difficulty_picker(
            ctx, gid, uid, skill["level"], dry_run=False, buffs=buffs
        )

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
        await self._send_difficulty_picker(
            ctx, ctx.guild.id, ctx.author.id, level, dry_run=True
        )

    async def _send_difficulty_picker(
        self, ctx: commands.Context, gid: int, uid: int, skill_level: int,
        *, dry_run: bool, buffs: dict | None = None,
    ) -> None:
        """Same Easy/Medium/Hard picker every other per-job minigame
        shows first (see cogs/minigames.py): Easy is always open,
        Medium/Hard unlock at formulas.DIFFICULTIES' thresholds in
        Alchemist skill. Picking a tier is what starts the brew (and,
        for a real run, burns the cooldown)."""
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=60)
        panel.header("🧪 The Cauldron Brew")
        panel.text(
            "*Pick your difficulty. Higher tiers run longer and hit "
            "harder, but pay far better.*"
        )
        # Same list style as .shop's tool ladder: icon, then a
        # fixed-width chip so the reward multiplier column lines up
        # down the page, whether a tier is open or still locked.
        lines = []
        buttons = []
        for key in formulas.DIFFICULTY_ORDER:
            tier = formulas.DIFFICULTIES[key]
            length = formulas.brew_sequence_length(key)
            unlocked = dry_run or formulas.difficulty_unlocked(skill_level, key)
            mult = f"×{tier['reward_mult']:.2f}"
            if unlocked:
                lines.append(
                    f"{tier['emoji']} {chip((tier['label'], NAME_W), (mult, -AMT_W))} "
                    f"· {length} reagents"
                )
            else:
                lines.append(
                    f"🔒 {chip((tier['label'], NAME_W), (mult, -AMT_W))} "
                    f"· unlocks lvl {tier['unlock_level']} (you're {skill_level})"
                )
            btn = ui.Button(
                label=tier["label"], emoji=tier["emoji"],
                style=discord.ButtonStyle.secondary, disabled=not unlocked,
            )
            btn.callback = self._make_difficulty_handler(
                key, dry_run=dry_run, buffs=buffs, level=skill_level,
            )
            buttons.append(btn)
        panel.text("\n".join(lines))
        panel.buttons(*buttons)
        message = await ctx.send(view=panel)
        panel.message = message

    def _make_difficulty_handler(
        self, difficulty: str, *, dry_run: bool, buffs: dict | None, level: int,
    ):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            if dry_run:
                session = BrewSession(
                    self.db, gid, uid, level, 0, 0, dry_run=True, difficulty=difficulty
                )
                await self._run_brew(
                    InteractionSender(interaction), session, test_mode=True
                )
                return

            now = time.time()
            cooldown = apply_cooldown_buff(formulas.BREW_COOLDOWN, buffs)
            user = await self.db.get_user(gid, uid)
            if now < user["last_brew"] + cooldown:
                await interaction.response.edit_message(
                    view=simple_panel(
                        "Too late, the cauldron's cooling again.", accent=Palette.RED
                    )
                )
                return

            # The cooldown burns the moment the brew starts, win or
            # lose, so walking away mid-brew can't reroll a bad sequence.
            await self.db.set_last_brew(gid, uid, now)
            skill = await self.db.get_skill(gid, uid, "alchemist")
            session = BrewSession(
                self.db, gid, uid, skill["level"], skill["xp"], skill["last_work"],
                buffs=buffs, difficulty=difficulty,
            )
            await self._run_brew(InteractionSender(interaction), session)
        return handler

    async def _run_brew(
        self, sendable, session: BrewSession, *, test_mode: bool = False
    ) -> None:
        """Shared reveal-then-answer flow for both .brew and .brewtest.
        `sendable` is anything with an async .send(view=...) -> Message
        (commands.Context is never used here directly any more --
        every call now arrives via InteractionSender from the
        difficulty picker's button, but the shape is kept generic)."""
        panel = Panel(accent=Palette.PURPLE, timeout=None)
        panel.header("🧪 The Cauldron Brew")
        if test_mode:
            panel.text("🧪 *TEST MODE, no job, cooldown, or rewards apply.*")
        panel.text(
            f"{session.tier['emoji']} {session.tier['label']} · "
            f"Sequence length: **{session.length}** reagents"
        )
        panel.footer("👀 watch closely, and remember the order")
        message = await sendable.send(view=panel)

        for revealed in range(1, session.length + 1):
            await asyncio.sleep(session.reveal_delay)
            reagent = session.sequence[revealed - 1]
            flash = Panel(accent=Palette.PURPLE, timeout=None)
            flash.header("🧪 The Cauldron Brew")
            flash.text(f"Reagent {revealed}/{session.length}")
            flash.text(f"# {REAGENTS[reagent]}")
            try:
                await message.edit(view=flash)
            except discord.HTTPException:
                return
        await asyncio.sleep(session.reveal_delay)

        answer_panel = session.answer_panel()
        answer_panel.message = message
        await message.edit(view=answer_panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Brew(bot))
