"""The other per-job minigames, one cousin of the cauldron brew per
trade -- including the Criminal trade's own .rob. Each is quick,
timed, and fails the instant you mistap or run out of time; reward is
proportional to how far you got, built on the same shared curve as
.brew (formulas.roll_minigame_reward). Each has an admin test command,
exactly like .brewtest.

Access follows the same rule as .brew: your current job always
qualifies, or MINIGAME_MIN_LEVEL_WITHOUT_JOB in that trade's skill
even without holding the job (persists across job switches).

.rob is the odd one out: it needs an "are you sure?" confirmation
before it starts (config["requires_confirm"]), doesn't touch fame, and
resolves through infamy instead -- a success grants a big chunk of it,
getting caught (any fail) wipes it back to 0. Every other minigame
here grants a little fame on success and gets a fame-scaled bonus,
same shape as infamy's bonus to Criminal, opposite realm.
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
from ui.panels import AMT_W, NAME_W, Palette, Panel, RoundPanel, chip, simple_panel


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
        """outcome is one of 'success', 'banked', or 'fail'.

        Criminal (.rob) and every other trade's minigame draw on
        opposite reputation tracks: Criminal's payout scales with
        infamy and a failed run gets caught, resetting infamy to 0;
        every other trade's payout scales with fame, and a success
        grants a little more of it. See formulas.py's infamy/fame
        section for the full rationale."""
        is_criminal = self.job_key == "criminal"
        user = await self.db.get_user(self.gid, self.uid)
        total = await self.db.total_level(self.gid, self.uid)
        # Criminal itself unlocks free (0), but .rob should pay like the
        # single biggest score in the game, not a starter trade -- the
        # config can override which unlock tier the reward floor uses.
        unlock = self.config.get(
            "reward_tier_level", JOBS[self.job_key]["unlock_total_level"]
        )
        extra_mult = (
            formulas.infamy_multiplier(user["infamy"]) if is_criminal
            else formulas.fame_multiplier(user["fame"])
        )
        reward, perfect = formulas.roll_minigame_reward(
            self.correct, self.length, unlock, MAX_JOB_UNLOCK_LEVEL,
            self.level, total, perfect_bonus=formulas.MINIGAME_PERFECT_BONUS,
            extra_multiplier=extra_mult,
        )
        xp_gain = self.correct * formulas.MINIGAME_XP_PER_ROUND
        new_level, new_xp, levels_gained = formulas.apply_xp(self.level, self.xp, xp_gain)

        caught = is_criminal and outcome == "fail"
        infamy_note: str | None = None
        fame_gained = 0

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

            if is_criminal:
                if outcome == "success":
                    gained = random.randint(
                        formulas.ROB_SUCCESS_INFAMY_MIN, formulas.ROB_SUCCESS_INFAMY_MAX
                    )
                    await self.db.add_infamy(self.gid, self.uid, gained)
                    infamy_note = f"+{gained} infamy"
                elif caught:
                    await self.db.set_infamy(self.gid, self.uid, 0)
                    infamy_note = "infamy reset to 0"
            elif outcome == "success":
                await self.db.add_fame(self.gid, self.uid, formulas.MINIGAME_FAME_ON_SUCCESS)
                fame_gained = formulas.MINIGAME_FAME_ON_SUCCESS

        title = self.config["title"]
        if outcome == "success":
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header(f"{title} · A Flawless Run!" if perfect else f"{title} · Complete")
            panel.text(f"*{extra_text or self.config['success_text']}*")
        elif outcome == "banked":
            panel = Panel(accent=Palette.GOLD, timeout=None)
            panel.header(f"{title} · Pulled Early")
            panel.text(f"*{extra_text or 'You stop while you can still call it a win.'}*")
        elif caught:
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header(f"{title} · Caught!")
            panel.text(
                "*Alarm bells ring out and guards swarm the vault. You "
                "barely escape with your life, but your reputation is "
                "in ruins.*"
            )
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
        if fame_gained:
            footer += f" · 🌟 +{fame_gained} fame"
        if infamy_note:
            footer += f" · 🗡️ {infamy_note}"
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
        self.current_panel: RoundPanel | None = None
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
        self.current_panel: RoundPanel | None = None

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
        self.current_panel = panel
        return panel

    async def _on_add(self, interaction: discord.Interaction) -> None:
        if self.done:
            await interaction.response.defer()
            return
        # See MatchSession.on_tap: stop the old view's background timer
        # explicitly so it can't outlive this round and misfire later.
        if self.current_panel is not None:
            self.current_panel.stop()
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
        if self.current_panel is not None:
            self.current_panel.stop()
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


class _InteractionSender:
    """Adapts a component interaction to the ctx.send(view=...) shape a
    session's start-up expects, for the one-shot "confirm -> the game
    replaces that same message" flow used by .rob."""

    def __init__(self, interaction: discord.Interaction):
        self.interaction = interaction

    async def send(self, view=None, **kwargs) -> discord.Message:
        await self.interaction.response.edit_message(view=view)
        return self.interaction.message


class Minigames(commands.Cog):
    """The other per-job minigames beyond the cauldron brew."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @staticmethod
    def _cooldown_for(job_key: str, config: dict) -> int:
        """Most minigames use the usual unlock-tier cooldown curve; a
        config can set a flat "cooldown" to override it (.rob is a
        flat 12h, not the ~45min a free-to-start trade would otherwise
        get from that formula)."""
        if "cooldown" in config:
            return config["cooldown"]
        return formulas.minigame_cooldown(
            JOBS[job_key]["unlock_total_level"], MAX_JOB_UNLOCK_LEVEL
        )

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
            await self._send_session(ctx, gid, uid, job_key, config, level, 0, 0, dry_run=True)
            return

        if not await self._check_access(ctx, job_key):
            return
        now = time.time()
        cooldown = self._cooldown_for(job_key, config)
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

        if config.get("requires_confirm"):
            # Cooldown isn't burned until Confirm is actually pressed --
            # declining, or just looking, shouldn't cost the attempt.
            await self._send_confirm(ctx, job_key, config)
            return

        # The cooldown burns the moment the attempt starts, win or
        # lose, so walking away mid-attempt can't reroll a bad run.
        await self.db.set_minigame_cooldown(gid, uid, job_key, now)
        skill = await self.db.get_skill(gid, uid, job_key)
        await self._send_session(
            ctx, gid, uid, job_key, config,
            skill["level"], skill["xp"], skill["last_work"], dry_run=False,
        )

    async def _send_session(
        self, sendable, gid: int, uid: int, job_key: str, config: dict,
        session_level: int, xp: int, last_work: float, *, dry_run: bool,
    ) -> None:
        """`sendable` is anything with an async .send(view=...) -> Message
        (commands.Context, or _InteractionSender for the .rob confirm
        flow)."""
        session_cls = SESSION_CLASSES[config["kind"]]
        session = session_cls(
            self.db, gid, uid, job_key, session_level, xp, last_work, dry_run=dry_run,
        )

        if dry_run:
            await sendable.send(
                view=simple_panel(
                    f"🧪 *TEST MODE for {config['title']}, no job, cooldown, "
                    "or rewards apply.*",
                    accent=Palette.PURPLE,
                )
            )

        if isinstance(session, FishSession):
            await session.run(sendable)
        else:
            panel = session.round_panel()
            message = await sendable.send(view=panel)
            panel.message = message

    async def _send_confirm(
        self, ctx: commands.Context, job_key: str, config: dict
    ) -> None:
        """The one-way door before .rob: get caught and infamy resets to
        0, so make sure the player actually meant to press the button."""
        panel = Panel(accent=Palette.RED, author_id=ctx.author.id, timeout=30)
        panel.header(f"{config['title']} · Are You Sure?")
        panel.text(
            "*This isn't like the others. Get caught, and everything "
            "you've built goes up in smoke, your infamy resets to 0.*"
        )
        confirm_btn = ui.Button(label="Do It", emoji="🏦", style=discord.ButtonStyle.danger)
        cancel_btn = ui.Button(label="Walk Away", style=discord.ButtonStyle.secondary)

        async def on_confirm(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            now = time.time()
            cooldown = self._cooldown_for(job_key, config)
            last = await self.db.get_minigame_cooldown(gid, uid, job_key)
            if now < last + cooldown:
                await interaction.response.edit_message(
                    view=simple_panel(
                        "Too late, the window's closed for now.", accent=Palette.RED
                    )
                )
                return
            await self.db.set_minigame_cooldown(gid, uid, job_key, now)
            skill = await self.db.get_skill(gid, uid, job_key)
            await self._send_session(
                _InteractionSender(interaction), gid, uid, job_key, config,
                skill["level"], skill["xp"], skill["last_work"], dry_run=False,
            )

        async def on_cancel(interaction: discord.Interaction) -> None:
            await interaction.response.edit_message(
                view=simple_panel(
                    "You think better of it and walk away.", accent=Palette.GOLD
                )
            )

        confirm_btn.callback = on_confirm
        cancel_btn.callback = on_cancel
        panel.buttons(confirm_btn, cancel_btn)
        panel.message = await ctx.send(view=panel)

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

    # ── criminal: rob ───────────────────────────────────────────────────

    @commands.hybrid_command(
        name="rob", description="Criminal minigame: rob the bank vault for the biggest score in town"
    )
    @commands.guild_only()
    async def rob(self, ctx: commands.Context):
        await self._play(ctx, "criminal")

    @commands.hybrid_command(
        name="robtest", description="[Admin] Try the bank job with no job/cooldown/rewards/confirm"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Criminal level to simulate (default: 1)")
    async def robtest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "criminal", level=level, dry_run=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Minigames(bot))
