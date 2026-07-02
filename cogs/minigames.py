"""The other seven per-job minigames, one cousin of the cauldron brew
per trade. Each is quick, timed, and fails the instant you mistap or
run out of time; reward is proportional to how far you got, built on
the same shared curve as .brew (formulas.roll_minigame_reward). Each
has an admin test command, exactly like .brewtest.

Access follows the same rule as .brew: your current job always
qualifies, or MINIGAME_MIN_LEVEL_WITHOUT_JOB in that trade's skill
even without holding the job (persists across job switches).
"""

from __future__ import annotations

import asyncio
import random
import time

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import formulas
from econ.data.jobs import JOBS, MAX_JOB_UNLOCK_LEVEL
from econ.data.minigames import MINIGAMES
from ui.panels import AMT_W, NAME_W, Palette, Panel, chip, simple_panel


class RoundPanel(Panel):
    """A Panel whose expiry resolves the owning minigame session as a
    timeout failure, instead of the base Panel's disable-in-place."""

    def __init__(self, session: "BaseMinigameSession", **kwargs):
        super().__init__(**kwargs)
        self.session = session

    async def on_timeout(self) -> None:
        message = getattr(self, "message", None)
        if message is not None:
            await self.session.on_round_timeout(message)


class BaseMinigameSession:
    """Shared reward math, XP, and result-panel rendering for every
    per-job minigame. Subclasses only need to drive their own round
    flow and call `_finish()` when the attempt ends."""

    def __init__(
        self, db, gid: int, uid: int, job_key: str, level: int, xp: int,
        last_work: float, *, dry_run: bool = False,
    ):
        self.db = db
        self.gid = gid
        self.uid = uid
        self.job_key = job_key
        self.config = MINIGAMES[job_key]
        self.level = level
        self.xp = xp
        self.last_work = last_work
        self.dry_run = dry_run
        self.length = formulas.minigame_length(
            level, self.config["min_len"], self.config["max_len"],
            self.config["level_per_step"],
        )
        self.correct = 0
        self.done = False

    def _footer_text(self, text: str) -> str:
        return f"🧪 TEST MODE · {text}" if self.dry_run else text

    async def _finish(
        self, *, outcome: str, fail_text: str | None = None, extra_text: str | None = None,
    ) -> Panel:
        """outcome is one of 'success', 'banked', or 'fail'."""
        total = await self.db.total_level(self.gid, self.uid)
        unlock = JOBS[self.job_key]["unlock_total_level"]
        reward, perfect = formulas.roll_minigame_reward(
            self.correct, self.length, unlock, MAX_JOB_UNLOCK_LEVEL,
            self.level, total, perfect_bonus=formulas.MINIGAME_PERFECT_BONUS,
        )
        xp_gain = self.correct * formulas.MINIGAME_XP_PER_ROUND
        new_level, new_xp, levels_gained = formulas.apply_xp(self.level, self.xp, xp_gain)

        if not self.dry_run:
            await self.db.update_skill(
                self.gid, self.uid, self.job_key, new_level, new_xp, self.last_work
            )
            if reward:
                await self.db.add_gold(self.gid, self.uid, reward)
            cmd = self.config["command"]
            await self.db.incr_stat(self.gid, self.uid, f"{cmd}_completed")
            if perfect:
                await self.db.incr_stat(self.gid, self.uid, f"{cmd}_perfect")
            if reward:
                await self.db.incr_stat(self.gid, self.uid, f"gold_from_{cmd}", reward)

        title = self.config["title"]
        if outcome == "success":
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header(f"{title} · A Flawless Run!" if perfect else f"{title} · Complete")
            panel.text(f"*{extra_text or self.config['success_text']}*")
        elif outcome == "banked":
            panel = Panel(accent=Palette.GOLD, timeout=None)
            panel.header(f"{title} · Pulled Early")
            panel.text(f"*{extra_text or 'You stop while you can still call it a win.'}*")
        else:
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header(f"{title} · It Slips Away")
            panel.text(f"*{fail_text or self.config['fail_text']}*")

        reward_line = (
            f"💰 {chip(('Reward', NAME_W), (f'{reward:,}', -AMT_W))} 🪙"
            if reward else "💰 No gold this time."
        )
        panel.text(reward_line)

        footer = f"{self.correct}/{self.length} rounds cleared"
        if xp_gain:
            footer += f" · +{xp_gain} XP"
        if levels_gained and not self.dry_run:
            footer += f" · ⭐ now level {new_level}"
        panel.footer(self._footer_text(footer))
        return panel

    async def on_round_timeout(self, message: discord.Message) -> None:
        """Fired when a RoundPanel expires unanswered. Not every kind
        uses RoundPanel (fish manages its own timing), but the ones
        that do all resolve the same way: a genuine, timed failure."""
        if self.done:
            return
        self.done = True
        panel = await self._finish(
            outcome="fail",
            fail_text="You hesitate a moment too long, and the chance slips away.",
        )
        try:
            await message.edit(view=panel)
        except discord.HTTPException:
            pass


class MatchSession(BaseMinigameSession):
    """Bot names a target among a handful of decoys; tap the right one
    before the timer runs out. Powers harvest, dig, fell, hunt, tend."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target: str | None = None
        self.choices: list[str] = []
        self._roll_round()

    def _roll_round(self) -> None:
        options = self.config["options"]
        keys = list(options)
        self.target = random.choice(keys)
        decoy_n = min(self.config["decoys"], len(keys) - 1)
        pool = [k for k in keys if k != self.target]
        self.choices = random.sample(pool, decoy_n) + [self.target]
        random.shuffle(self.choices)

    def round_panel(self) -> Panel:
        options = self.config["options"]
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        timeout = self.config["round_timeout"]
        panel = RoundPanel(self, accent=Palette.GOLD, author_id=self.uid, timeout=timeout)
        panel.header(self.config["title"])
        label = self.target.replace("_", " ").title()
        panel.text(f"{options[self.target]} **{label}** {self.config['prompt']}")
        panel.text(f"`{dots}`  ({self.correct}/{self.length})")
        buttons = []
        for key in self.choices:
            btn = ui.Button(emoji=options[key], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_handler(key)
            buttons.append(btn)
        # Discord caps an ActionRow at 5 components; split across rows.
        for i in range(0, len(buttons), 5):
            panel.buttons(*buttons[i : i + 5])
        deadline = int(time.time()) + timeout
        panel.footer(self._footer_text(f"⏱️ act by <t:{deadline}:R>"))
        return panel

    def _make_handler(self, key: str):
        async def handler(interaction: discord.Interaction) -> None:
            await self.on_tap(interaction, key)
        return handler

    async def on_tap(self, interaction: discord.Interaction, key: str) -> None:
        if self.done:
            await interaction.response.defer()
            return
        if key != self.target:
            self.done = True
            panel = await self._finish(outcome="fail")
            await interaction.response.edit_message(view=panel)
            return
        self.correct += 1
        if self.correct == self.length:
            self.done = True
            panel = await self._finish(outcome="success")
            await interaction.response.edit_message(view=panel)
            return
        self._roll_round()
        next_panel = self.round_panel()
        next_panel.message = interaction.message
        await interaction.response.edit_message(view=next_panel)


class FishSession(BaseMinigameSession):
    """Pure reflex: wait for the bite, then reel before the window
    closes. Tapping too early or too late both fail the whole cast."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase = "idle"  # idle -> biting -> resolved

    def _waiting_panel(self) -> Panel:
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        panel = Panel(accent=Palette.BLUE, author_id=self.uid, timeout=None)
        panel.header(self.config["title"])
        panel.text("🌊 *The line goes still. Watch close...*")
        panel.text(f"`{dots}`  ({self.correct}/{self.length})")
        btn = ui.Button(label="Reel In?", emoji="🎣", style=discord.ButtonStyle.secondary)
        btn.callback = self._on_reel
        panel.buttons(btn)
        panel.footer(self._footer_text("tap too soon and it'll spook"))
        return panel

    def _biting_panel(self, deadline: int) -> Panel:
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        panel = Panel(accent=Palette.GOLD, author_id=self.uid, timeout=None)
        panel.header(self.config["title"])
        panel.text("# 🎣 IT'S BITING!")
        panel.text(f"`{dots}`  ({self.correct}/{self.length})")
        btn = ui.Button(label="Reel In!", emoji="🎣", style=discord.ButtonStyle.success)
        btn.callback = self._on_reel
        panel.buttons(btn)
        panel.footer(self._footer_text(f"⏱️ reel by <t:{deadline}:R>"))
        return panel

    async def _on_reel(self, interaction: discord.Interaction) -> None:
        if self.done:
            await interaction.response.defer()
            return
        if self.phase != "biting":
            self.done = True
            panel = await self._finish(outcome="fail", fail_text=self.config["fail_early_text"])
            await interaction.response.edit_message(view=panel)
            return
        self.correct += 1
        self.phase = "resolved"
        if self.correct == self.length:
            self.done = True
            panel = await self._finish(outcome="success")
            await interaction.response.edit_message(view=panel)
        else:
            await interaction.response.edit_message(view=self._waiting_panel())

    async def run(self, ctx: commands.Context) -> None:
        message = await ctx.send(view=self._waiting_panel())
        while not self.done:
            self.phase = "idle"
            wait = random.uniform(self.config["wait_min"], self.config["wait_max"])
            await asyncio.sleep(wait)
            if self.done:
                return
            self.phase = "biting"
            deadline = int(time.time()) + self.config["reel_window"]
            try:
                await message.edit(view=self._biting_panel(deadline))
            except discord.HTTPException:
                return
            await asyncio.sleep(self.config["reel_window"])
            if self.done:
                return
            if self.phase == "biting":  # never tapped in time
                self.done = True
                panel = await self._finish(
                    outcome="fail", fail_text=self.config["fail_late_text"]
                )
                try:
                    await message.edit(view=panel)
                except discord.HTTPException:
                    pass
                return
            # phase == "resolved": a successful reel already re-rendered
            # the waiting panel via the interaction response, loop on


class BakeSession(BaseMinigameSession):
    """Press-your-luck: keep adding ingredients toward a hidden target.
    One scoop too many ruins the batch outright; stop early to bank a
    smaller, safer reward instead."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        jitter = random.choice([-1, 0, 0, 1])
        self.target = max(2, self.length + jitter)
        self.scoops = 0

    def _hint(self) -> str:
        if self.scoops == 0:
            return "The bowl is empty. Start folding in ingredients."
        if self.scoops >= self.target - 1:
            return "The dough feels heavy, almost too heavy..."
        if self.scoops >= max(1, self.target - 3):
            return "The dough is coming together nicely."
        return "Still thin, needs more."

    def round_panel(self) -> Panel:
        timeout = self.config["step_timeout"]
        panel = RoundPanel(self, accent=Palette.GOLD, author_id=self.uid, timeout=timeout)
        panel.header(self.config["title"])
        panel.text(f"*{self._hint()}*")
        plural = "s" if self.scoops != 1 else ""
        panel.text(f"🥄 {self.scoops} scoop{plural} folded in")
        add_btn = ui.Button(label="Add Ingredient", emoji="🥄", style=discord.ButtonStyle.secondary)
        add_btn.callback = self._on_add
        stop_btn = ui.Button(label="Into the Oven", emoji="🔥", style=discord.ButtonStyle.success)
        stop_btn.callback = self._on_stop
        panel.buttons(add_btn, stop_btn)
        deadline = int(time.time()) + timeout
        panel.footer(self._footer_text(f"⏱️ decide by <t:{deadline}:R>"))
        return panel

    async def _on_add(self, interaction: discord.Interaction) -> None:
        if self.done:
            await interaction.response.defer()
            return
        self.scoops += 1
        if self.scoops > self.target:
            self.done = True
            self.correct = 0
            panel = await self._finish(outcome="fail")
            await interaction.response.edit_message(view=panel)
            return
        self.correct = self.scoops
        if self.scoops == self.target:
            self.done = True
            panel = await self._finish(outcome="success")
            await interaction.response.edit_message(view=panel)
            return
        next_panel = self.round_panel()
        next_panel.message = interaction.message
        await interaction.response.edit_message(view=next_panel)

    async def _on_stop(self, interaction: discord.Interaction) -> None:
        if self.done:
            await interaction.response.defer()
            return
        self.done = True
        self.correct = self.scoops
        if self.scoops == 0:
            panel = await self._finish(
                outcome="fail",
                fail_text="You stop before adding a thing. There's nothing to bake.",
            )
        else:
            panel = await self._finish(outcome="banked")
        await interaction.response.edit_message(view=panel)


SESSION_CLASSES = {"match": MatchSession, "reflex": FishSession, "pressluck": BakeSession}


class Minigames(commands.Cog):
    """The seven per-job minigames beyond the cauldron brew."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    async def _check_access(self, ctx: commands.Context, job_key: str) -> bool:
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        if user["job"] == job_key:
            return True
        # Read-only: peeking must never create a phantom skill row for a
        # trade the player never worked (that would silently inflate
        # their total_level, the same bug .job info had before).
        skill = await self.db.peek_skill(gid, uid, job_key)
        if skill["level"] >= formulas.MINIGAME_MIN_LEVEL_WITHOUT_JOB:
            return True
        job_name = JOBS[job_key]["name"]
        await ctx.send(
            view=simple_panel(
                f"You are not a {job_name.lower()}, or high enough lvl "
                f"({formulas.MINIGAME_MIN_LEVEL_WITHOUT_JOB}) in it to do this "
                "without being one.",
                accent=Palette.RED,
            ),
            ephemeral=True,
        )
        return False

    async def _play(
        self, ctx: commands.Context, job_key: str,
        *, level: int = 1, dry_run: bool = False,
    ) -> None:
        gid, uid = ctx.guild.id, ctx.author.id
        config = MINIGAMES[job_key]

        if dry_run:
            session_level, xp, last_work = level, 0, 0
        else:
            if not await self._check_access(ctx, job_key):
                return
            now = time.time()
            cooldown = formulas.minigame_cooldown(
                JOBS[job_key]["unlock_total_level"], MAX_JOB_UNLOCK_LEVEL
            )
            last = await self.db.get_minigame_cooldown(gid, uid, job_key)
            ready_at = last + cooldown
            if now < ready_at:
                await ctx.send(
                    view=simple_panel(
                        f"{config['title']} is still recovering. "
                        f"Ready <t:{int(ready_at)}:R>.",
                        accent=Palette.RED,
                    ),
                    ephemeral=True,
                )
                return
            # The cooldown burns the moment the attempt starts, win or
            # lose, so walking away mid-attempt can't reroll a bad run.
            await self.db.set_minigame_cooldown(gid, uid, job_key, now)
            skill = await self.db.get_skill(gid, uid, job_key)
            session_level, xp, last_work = skill["level"], skill["xp"], skill["last_work"]

        session_cls = SESSION_CLASSES[config["kind"]]
        session = session_cls(
            self.db, gid, uid, job_key, session_level, xp, last_work, dry_run=dry_run,
        )

        if dry_run:
            await ctx.send(
                view=simple_panel(
                    f"🧪 *TEST MODE for {config['title']}, no job, cooldown, "
                    "or rewards apply.*",
                    accent=Palette.PURPLE,
                )
            )

        if isinstance(session, FishSession):
            await session.run(ctx)
        else:
            panel = session.round_panel()
            message = await ctx.send(view=panel)
            panel.message = message

    # ── farmer: harvest ─────────────────────────────────────────────────

    @commands.hybrid_command(
        name="harvest", description="Farmer minigame: tap the ripe crop before it spoils"
    )
    @commands.guild_only()
    async def harvest(self, ctx: commands.Context):
        await self._play(ctx, "farmer")

    @commands.hybrid_command(
        name="harvesttest",
        description="[Admin] Try the harvest minigame with no job/cooldown/rewards",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Farmer level to simulate (default: 1)")
    async def harvesttest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "farmer", level=level, dry_run=True)

    # ── miner: dig ──────────────────────────────────────────────────────

    @commands.hybrid_command(
        name="dig", description="Miner minigame: follow the vein before it's lost"
    )
    @commands.guild_only()
    async def dig(self, ctx: commands.Context):
        await self._play(ctx, "miner")

    @commands.hybrid_command(
        name="digtest", description="[Admin] Try the dig minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Miner level to simulate (default: 1)")
    async def digtest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "miner", level=level, dry_run=True)

    # ── fisherman: fish ─────────────────────────────────────────────────

    @commands.hybrid_command(
        name="fish", description="Fisherman minigame: reel in the instant it bites"
    )
    @commands.guild_only()
    async def fish(self, ctx: commands.Context):
        await self._play(ctx, "fisherman")

    @commands.hybrid_command(
        name="fishtest", description="[Admin] Try the fish minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Fisherman level to simulate (default: 1)")
    async def fishtest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "fisherman", level=level, dry_run=True)

    # ── lumberjack: fell ────────────────────────────────────────────────

    @commands.hybrid_command(
        name="fell", description="Lumberjack minigame: swing the side the trunk leans"
    )
    @commands.guild_only()
    async def fell(self, ctx: commands.Context):
        await self._play(ctx, "lumberjack")

    @commands.hybrid_command(
        name="felltest", description="[Admin] Try the fell minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Lumberjack level to simulate (default: 1)")
    async def felltest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "lumberjack", level=level, dry_run=True)

    # ── hunter: hunt ────────────────────────────────────────────────────

    @commands.hybrid_command(
        name="hunt", description="Hunter minigame: loose your arrow at the right prey"
    )
    @commands.guild_only()
    async def hunt(self, ctx: commands.Context):
        await self._play(ctx, "hunter")

    @commands.hybrid_command(
        name="hunttest", description="[Admin] Try the hunt minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Hunter level to simulate (default: 1)")
    async def hunttest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "hunter", level=level, dry_run=True)

    # ── baker: bake ─────────────────────────────────────────────────────

    @commands.hybrid_command(
        name="bake", description="Baker minigame: press your luck on the perfect batch"
    )
    @commands.guild_only()
    async def bake(self, ctx: commands.Context):
        await self._play(ctx, "baker")

    @commands.hybrid_command(
        name="baketest", description="[Admin] Try the bake minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Baker level to simulate (default: 1)")
    async def baketest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "baker", level=level, dry_run=True)

    # ── brewer: tend ────────────────────────────────────────────────────

    @commands.hybrid_command(
        name="tend", description="Brewer minigame: tap the vat that's ready before it spoils"
    )
    @commands.guild_only()
    async def tend(self, ctx: commands.Context):
        await self._play(ctx, "brewer")

    @commands.hybrid_command(
        name="tendtest", description="[Admin] Try the tend minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Brewer level to simulate (default: 1)")
    async def tendtest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "brewer", level=level, dry_run=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Minigames(bot))
