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
from econ.buffs import (
    active_buff_summary,
    active_buff_totals,
    apply_cooldown_buff,
    apply_gold_buff,
    apply_xp_buff,
)
from econ.data.jobs import JOBS, MAX_JOB_UNLOCK_LEVEL
from econ.data.minigames import MINIGAMES, pick_flavor
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


# Shared flavour pools every session kind draws on, so repeated runs
# don't read like the same form letter (per-game success/fail variants
# live in econ/data/minigames.py; these are the outcome-agnostic ones).
TIMEOUT_TEXTS = [
    "You hesitate a moment too long, and the chance slips away.",
    "The moment comes and goes while you're still deciding.",
    "Time's up. Whatever you were waiting for, it wasn't this.",
]
BANKED_TEXTS = [
    "You stop while you can still call it a win.",
    "Quit while you're ahead, there's wisdom in that.",
    "Not the grandest haul, but it's yours, safe and counted.",
]
NEAR_MISS_TEXTS = [
    "One round short. It was nearly yours.",
    "So close you could taste it.",
    "Next time. You know you had it.",
]
CAUGHT_TEXTS = [
    "Alarm bells ring out and guards swarm the vault. You barely escape "
    "with your life, but your reputation is in ruins.",
    "A whistle, then shouting, then every door in the bank slams shut. You "
    "slip out a window with nothing, and everyone knows your face now.",
    "They were waiting for you. You run until your lungs burn, and by "
    "dawn your name is worthless in every den in town.",
]


class BaseMinigameSession:
    """Shared reward math, XP, and result-panel rendering for every
    per-job minigame. Subclasses only need to drive their own round
    flow and call `_finish()` when the attempt ends.

    `difficulty` ("easy"/"medium"/"hard", see formulas.DIFFICULTIES) is
    chosen up front by the Easy/Medium/Hard picker every minigame
    command shows first: it fixes this attempt's round count (via
    formulas.difficulty_length) and is exposed as `self.tier` so
    subclasses can also tighten their own timers or add their own
    kind-specific extra challenge (self.tier["bonus"])."""

    def __init__(
        self, db, gid: int, uid: int, job_key: str, level: int, xp: int,
        last_work: float, *, dry_run: bool = False, buffs: dict | None = None,
        difficulty: str = "easy", ready_at: float | None = None,
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
        self.buffs = buffs or {}
        self.difficulty = difficulty
        # When the cooldown burned at the start of this attempt lets the
        # player go again -- shown on the result panel so a grinder
        # never has to run the command just to get told "not yet".
        self.ready_at = ready_at
        self.tier = formulas.DIFFICULTIES[difficulty]
        self.length = formulas.difficulty_length(
            self.config["min_len"], self.config["max_len"], difficulty
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
        cmd = self.config["command"]
        stats = {} if self.dry_run else await self.db.get_stats(self.gid, self.uid)
        prev_streak = stats.get(f"{cmd}_streak", 0)
        # Criminal itself unlocks free (0), but .rob should pay like the
        # single biggest score in the game, not a starter trade -- the
        # config can override which unlock tier the reward floor uses.
        unlock = self.config.get(
            "reward_tier_level", JOBS[self.job_key]["unlock_total_level"]
        )
        rep_mult = (
            formulas.infamy_multiplier(formulas.reputation_infamy(user["reputation"]))
            if is_criminal
            else formulas.fame_multiplier(formulas.reputation_fame(user["reputation"]))
        )
        extra_mult = (
            rep_mult * self.tier["reward_mult"] * formulas.streak_multiplier(prev_streak)
        )
        reward, perfect = formulas.roll_minigame_reward(
            self.correct, self.length, unlock, MAX_JOB_UNLOCK_LEVEL,
            self.level, total, perfect_bonus=formulas.MINIGAME_PERFECT_BONUS,
            extra_multiplier=extra_mult,
        )
        reward = round(apply_gold_buff(reward, self.buffs))
        xp_gain = round(apply_xp_buff(self.correct * formulas.MINIGAME_XP_PER_ROUND, self.buffs))
        new_level, new_xp, levels_gained = formulas.apply_xp(self.level, self.xp, xp_gain)

        caught = is_criminal and outcome == "fail"
        infamy_note: str | None = None
        fame_gained = 0
        perfect_count = stats.get(f"{cmd}_perfect", 0) + (1 if perfect else 0)
        # Success extends the hot streak, a fail breaks it; banking early
        # (bake's oven) does neither -- a cautious win shouldn't cost the
        # streak, but it shouldn't build one either.
        new_streak = prev_streak
        if outcome == "success":
            new_streak = prev_streak + 1
        elif outcome == "fail":
            new_streak = 0

        if not self.dry_run:
            await self.db.update_skill(
                self.gid, self.uid, self.job_key, new_level, new_xp, self.last_work
            )
            if reward:
                await self.db.add_gold(self.gid, self.uid, reward)
            await self.db.incr_stat(self.gid, self.uid, f"{cmd}_completed")
            if perfect:
                await self.db.incr_stat(self.gid, self.uid, f"{cmd}_perfect")
            if reward:
                await self.db.incr_stat(self.gid, self.uid, f"gold_from_{cmd}", reward)
            if new_streak != prev_streak:
                await self.db.set_stat(self.gid, self.uid, f"{cmd}_streak", new_streak)
                if new_streak > stats.get(f"{cmd}_best_streak", 0):
                    await self.db.set_stat(
                        self.gid, self.uid, f"{cmd}_best_streak", new_streak
                    )

            if is_criminal:
                if outcome == "success":
                    gained = random.randint(
                        formulas.ROB_SUCCESS_INFAMY_MIN, formulas.ROB_SUCCESS_INFAMY_MAX
                    )
                    new_rep = await self.db.add_reputation(self.gid, self.uid, -gained)
                    infamy_note = (
                        f"+{gained} infamy ({formulas.reputation_infamy(new_rep):,} total)"
                    )
                elif caught:
                    await self.db.set_reputation(self.gid, self.uid, 0)
                    infamy_note = "reputation reset to 0"
            elif outcome == "success":
                await self.db.add_reputation(self.gid, self.uid, formulas.MINIGAME_FAME_ON_SUCCESS)
                fame_gained = formulas.MINIGAME_FAME_ON_SUCCESS

        title = self.config["title"]
        if outcome == "success":
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header(f"{title} · A Flawless Run!" if perfect else f"{title} · Complete")
            panel.text(f"*{pick_flavor(extra_text or self.config['success_text'])}*")
        elif outcome == "banked":
            panel = Panel(accent=Palette.GOLD, timeout=None)
            panel.header(f"{title} · Pulled Early")
            panel.text(f"*{pick_flavor(extra_text) if extra_text else random.choice(BANKED_TEXTS)}*")
        elif caught:
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header(f"{title} · Caught!")
            panel.text(f"*{random.choice(CAUGHT_TEXTS)}*")
        else:
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header(f"{title} · It Slips Away")
            panel.text(f"*{pick_flavor(fail_text or self.config['fail_text'])}*")
            if self.correct == self.length - 1 and self.length >= 2:
                panel.text(f"-# {random.choice(NEAR_MISS_TEXTS)}")

        reward_line = (
            f"💰 {chip(('Reward', NAME_W), (f'{reward:,}', -AMT_W))} 🪙"
            if reward else "💰 No gold this time."
        )
        panel.text(reward_line)

        footer = f"{self.tier['emoji']} {self.tier['label']} · {self.correct}/{self.length} rounds cleared"
        if xp_gain:
            footer += f" · +{xp_gain} XP"
        if levels_gained and not self.dry_run:
            footer += f" · ⭐ now level {new_level}"
        if perfect and not self.dry_run:
            footer += f" · ✨ flawless run #{perfect_count}"
        if fame_gained:
            footer += f" · 🌟 +{fame_gained} fame"
        if infamy_note:
            footer += f" · 🗡️ {infamy_note}"
        if not self.dry_run:
            if new_streak >= 2:
                next_pct = round((formulas.streak_multiplier(new_streak) - 1) * 100)
                footer += f" · 🔥 {new_streak} in a row (+{next_pct}% gold next run)"
            elif outcome == "fail" and prev_streak >= 2:
                footer += f" · 💔 streak of {prev_streak} broken"
        buff_line = active_buff_summary(self.buffs)
        if buff_line:
            footer += f"\n✨ active: {buff_line}"
        if self.ready_at and not self.dry_run:
            footer += f"\n⏳ ready again <t:{int(self.ready_at)}:R>"
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
            outcome="fail", fail_text=random.choice(TIMEOUT_TEXTS),
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
        # Harder tiers throw in extra decoys -- more to scan through in
        # the same tight window, on top of that window itself shrinking.
        decoy_n = min(self.config["decoys"] + self.tier["bonus"], len(keys) - 1)
        pool = [k for k in keys if k != self.target]
        self.choices = random.sample(pool, decoy_n) + [self.target]
        random.shuffle(self.choices)

    def round_panel(self) -> Panel:
        options = self.config["options"]
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        timeout = max(1.0, self.config["round_timeout"] * self.tier["timeout_mult"])
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
        deadline = int(time.time() + timeout)
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

    WAIT_TEXTS = [
        "The line goes still. Watch close...",
        "The float bobs once, then nothing. Wait for it...",
        "Ripples spread and fade. Something's down there...",
        "The water's gone glassy. Any second now...",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase = "idle"  # idle -> biting -> resolved
        # Harder tiers give a shorter window to reel it in.
        self.reel_window = max(0.8, self.config["reel_window"] * self.tier["timeout_mult"])

    def _waiting_panel(self) -> Panel:
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        panel = Panel(accent=Palette.BLUE, author_id=self.uid, timeout=None)
        panel.header(self.config["title"])
        panel.text(f"🌊 *{random.choice(self.WAIT_TEXTS)}*")
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
            deadline = int(time.time() + self.reel_window)
            try:
                await message.edit(view=self._biting_panel(deadline))
            except discord.HTTPException:
                return
            await asyncio.sleep(self.reel_window)
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

    # One pool per "how close to the hidden target" band -- the BAND is
    # the signal a player reads, so variants within a band must all say
    # the same thing, just not in the same words every run.
    HINTS_EMPTY = [
        "The bowl is empty. Start folding in ingredients.",
        "A bare bowl and a full pantry. Get folding.",
    ]
    HINTS_NEAR = [
        "The dough feels heavy, almost too heavy...",
        "It's dense now. One more could be one too many...",
        "The spoon drags. You're right at the edge of it...",
    ]
    HINTS_MID = [
        "The dough is coming together nicely.",
        "Getting there, it's starting to hold its shape.",
        "Not bad. A few more folds and it'll be close.",
    ]
    HINTS_THIN = [
        "Still thin, needs more.",
        "Far too loose. Keep adding.",
        "It's barely batter yet. More.",
    ]

    def _hint(self) -> str:
        if self.scoops == 0:
            return random.choice(self.HINTS_EMPTY)
        if self.scoops >= self.target - 1:
            return random.choice(self.HINTS_NEAR)
        if self.scoops >= max(1, self.target - 3):
            return random.choice(self.HINTS_MID)
        return random.choice(self.HINTS_THIN)

    def round_panel(self) -> Panel:
        timeout = max(1.0, self.config["step_timeout"] * self.tier["timeout_mult"])
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
        deadline = int(time.time() + timeout)
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


class SpotDiffSession(BaseMinigameSession):
    """A grid of near-identical tiles hides one that looks *just*
    subtly different -- unlike MatchSession, the bot never names the
    target, you have to actually scan the grid and spot it yourself.
    Powers stretch (Tanner)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Harder tiers add more tiles to scan through, on top of the
        # shrinking round_timeout below.
        self.grid_size = self.config["grid_size"] + self.tier["bonus"] * 2
        self.target_index = 0
        self.current_panel: RoundPanel | None = None
        self._roll_round()

    def _roll_round(self) -> None:
        self.target_index = random.randrange(self.grid_size)

    def round_panel(self) -> Panel:
        cfg = self.config
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        timeout = max(1.0, cfg["round_timeout"] * self.tier["timeout_mult"])
        panel = RoundPanel(self, accent=Palette.GOLD, author_id=self.uid, timeout=timeout)
        panel.header(cfg["title"])
        panel.text("*One spot looks just a little different. Find it!*")
        panel.text(f"`{dots}`  ({self.correct}/{self.length})")
        buttons = []
        for i in range(self.grid_size):
            emoji = cfg["odd_emoji"] if i == self.target_index else cfg["common_emoji"]
            btn = ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary)
            btn.callback = self._make_handler(i)
            buttons.append(btn)
        for i in range(0, len(buttons), 5):
            panel.buttons(*buttons[i : i + 5])
        deadline = int(time.time() + timeout)
        panel.footer(self._footer_text(f"⏱️ act by <t:{deadline}:R>"))
        self.current_panel = panel
        return panel

    def _make_handler(self, index: int):
        async def handler(interaction: discord.Interaction) -> None:
            await self.on_tap(interaction, index)
        return handler

    async def on_tap(self, interaction: discord.Interaction, index: int) -> None:
        if self.done:
            await interaction.response.defer()
            return
        if self.current_panel is not None:
            self.current_panel.stop()
        if index != self.target_index:
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


class PairsSession(BaseMinigameSession):
    """A face-down grid of gems: flip two tiles at a time. A match
    stays revealed and banks progress; a mismatch ends the attempt
    right there, same one-mistake-and-done rule as every other
    minigame, just applied to memory instead of reflexes. Powers facet
    (Jeweler)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        gems = list(self.config["gems"])
        chosen = random.sample(gems, min(self.length, len(gems)))
        self.grid: list[str] = chosen * 2
        random.shuffle(self.grid)
        self.length = len(chosen)  # grid may be smaller than min_len if gems run out
        self.matched: set[int] = set()
        self.first_pick: int | None = None
        self.current_panel: RoundPanel | None = None

    def round_panel(self) -> Panel:
        cfg = self.config
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        timeout = max(2.0, cfg["round_timeout"] * self.tier["timeout_mult"])
        panel = RoundPanel(self, accent=Palette.GOLD, author_id=self.uid, timeout=timeout)
        panel.header(cfg["title"])
        hint = (
            "Pick a second tile to find its match."
            if self.first_pick is not None else
            "Flip two tiles to find a pair."
        )
        panel.text(f"*{hint}*")
        panel.text(f"`{dots}`  ({self.correct}/{self.length} pairs)")
        buttons = []
        for i, gem in enumerate(self.grid):
            revealed = i in self.matched or i == self.first_pick
            emoji = cfg["gems"][gem] if revealed else cfg["hidden_emoji"]
            style = (
                discord.ButtonStyle.success if i in self.matched
                else discord.ButtonStyle.secondary
            )
            btn = ui.Button(emoji=emoji, style=style, disabled=(i in self.matched))
            btn.callback = self._make_handler(i)
            buttons.append(btn)
        for i in range(0, len(buttons), 5):
            panel.buttons(*buttons[i : i + 5])
        deadline = int(time.time() + timeout)
        panel.footer(self._footer_text(f"⏱️ act by <t:{deadline}:R>"))
        self.current_panel = panel
        return panel

    def _make_handler(self, index: int):
        async def handler(interaction: discord.Interaction) -> None:
            await self.on_tap(interaction, index)
        return handler

    async def on_tap(self, interaction: discord.Interaction, index: int) -> None:
        if self.done or index in self.matched or index == self.first_pick:
            await interaction.response.defer()
            return
        if self.current_panel is not None:
            self.current_panel.stop()

        if self.first_pick is None:
            self.first_pick = index
            next_panel = self.round_panel()
            next_panel.message = interaction.message
            await interaction.response.edit_message(view=next_panel)
            return

        first, second = self.first_pick, index
        self.first_pick = None
        if self.grid[first] == self.grid[second]:
            self.matched.add(first)
            self.matched.add(second)
            self.correct += 1
            if self.correct == self.length:
                self.done = True
                panel = await self._finish(outcome="success")
                await interaction.response.edit_message(view=panel)
                return
            next_panel = self.round_panel()
            next_panel.message = interaction.message
            await interaction.response.edit_message(view=next_panel)
        else:
            self.done = True
            panel = await self._finish(outcome="fail")
            await interaction.response.edit_message(view=panel)


SESSION_CLASSES = {
    "match": MatchSession, "reflex": FishSession, "pressluck": BakeSession,
    "spotdiff": SpotDiffSession, "pairs": PairsSession,
}


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
            await self._send_difficulty_picker(ctx, gid, uid, job_key, config, level, dry_run=True)
            return

        if not await self._check_access(ctx, job_key):
            return
        buffs = await active_buff_totals(self.db, gid, uid)
        now = time.time()
        cooldown = apply_cooldown_buff(self._cooldown_for(job_key, config), buffs)
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

        # Cooldown isn't burned until a difficulty is actually picked --
        # declining, or just looking, shouldn't cost the attempt.
        skill = await self.db.get_skill(gid, uid, job_key)
        await self._send_difficulty_picker(
            ctx, gid, uid, job_key, config, skill["level"], dry_run=False, buffs=buffs,
        )

    async def _send_difficulty_picker(
        self, ctx: commands.Context, gid: int, uid: int, job_key: str, config: dict,
        skill_level: int, *, dry_run: bool, buffs: dict | None = None,
    ) -> None:
        """The first thing every minigame command shows: Easy is always
        open, Medium and Hard unlock at formulas.DIFFICULTIES'
        thresholds in that trade's own skill. Picking a tier is what
        actually starts the attempt (and, for a real run, burns the
        cooldown)."""
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=60)
        panel.header(config["title"])
        panel.text(
            "*Pick your difficulty. Higher tiers run longer and hit "
            "harder, but pay far better.*"
        )
        # Same list style as .shop's tool ladder: icon, then a
        # fixed-width chip so the payout column lines up down the page,
        # whether a tier is open or still locked. The number is what a
        # full clear would roughly pay THIS player right now -- a real
        # answer to "is Hard worth it?", not an abstract multiplier.
        total = await self.db.total_level(gid, uid)
        unlock = config.get("reward_tier_level", JOBS[job_key]["unlock_total_level"])
        lines = []
        buttons = []
        for key in formulas.DIFFICULTY_ORDER:
            tier = formulas.DIFFICULTIES[key]
            length = formulas.difficulty_length(config["min_len"], config["max_len"], key)
            unlocked = dry_run or formulas.difficulty_unlocked(skill_level, key)
            est = formulas.minigame_payout_estimate(
                unlock, MAX_JOB_UNLOCK_LEVEL, skill_level, total, tier["reward_mult"]
            )
            payout = f"~{est:,}"
            if unlocked:
                lines.append(
                    f"{tier['emoji']} {chip((tier['label'], NAME_W), (payout, -AMT_W))} 🪙 "
                    f"· {length} rounds"
                )
            else:
                lines.append(
                    f"🔒 {chip((tier['label'], NAME_W), (payout, -AMT_W))} 🪙 "
                    f"· unlocks lvl {tier['unlock_level']} (you're {skill_level})"
                )
            btn = ui.Button(
                label=tier["label"], emoji=tier["emoji"],
                style=discord.ButtonStyle.secondary, disabled=not unlocked,
            )
            btn.callback = self._make_difficulty_handler(
                job_key, config, key, dry_run=dry_run, buffs=buffs, level=skill_level,
            )
            buttons.append(btn)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._on_cancel
        buttons.append(cancel_btn)
        panel.text("\n".join(lines))
        panel.buttons(*buttons)
        cooldown = apply_cooldown_buff(self._cooldown_for(job_key, config), buffs or {})
        panel.footer(
            f"⏳ one attempt every ~{formulas.fmt_duration(cooldown)} · "
            "payouts are estimates, before fame, streaks, and a perfect bonus"
        )
        message = await ctx.send(view=panel)
        panel.message = message

    @staticmethod
    async def _on_cancel(interaction: discord.Interaction) -> None:
        """No difficulty was chosen, so nothing (cooldown, job checks)
        was ever spent -- just dismiss the picker."""
        await interaction.response.edit_message(
            view=simple_panel("You think better of it and walk away.", accent=Palette.GOLD)
        )

    def _make_difficulty_handler(
        self, job_key: str, config: dict, difficulty: str, *,
        dry_run: bool, buffs: dict | None, level: int,
    ):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            if dry_run:
                await self._send_session(
                    InteractionSender(interaction), gid, uid, job_key, config,
                    level, 0, 0, dry_run=True, difficulty=difficulty,
                )
                return

            now = time.time()
            cooldown = apply_cooldown_buff(self._cooldown_for(job_key, config), buffs)
            last = await self.db.get_minigame_cooldown(gid, uid, job_key)
            if now < last + cooldown:
                await interaction.response.edit_message(
                    view=simple_panel(
                        "Too late, the window's closed for now.", accent=Palette.RED
                    )
                )
                return

            if config.get("requires_confirm"):
                await self._send_confirm(interaction, job_key, config, difficulty, buffs)
                return

            # The cooldown burns the moment the attempt starts, win or
            # lose, so walking away mid-attempt can't reroll a bad run.
            await self.db.set_minigame_cooldown(gid, uid, job_key, now)
            skill = await self.db.get_skill(gid, uid, job_key)
            await self._send_session(
                InteractionSender(interaction), gid, uid, job_key, config,
                skill["level"], skill["xp"], skill["last_work"],
                dry_run=False, buffs=buffs, difficulty=difficulty,
                ready_at=now + cooldown,
            )
        return handler

    async def _send_session(
        self, sendable, gid: int, uid: int, job_key: str, config: dict,
        session_level: int, xp: int, last_work: float, *, dry_run: bool,
        buffs: dict | None = None, difficulty: str = "easy",
        ready_at: float | None = None,
    ) -> None:
        """`sendable` is anything with an async .send(view=...) -> Message
        (commands.Context, or InteractionSender for the difficulty-pick
        and .rob confirm flows)."""
        session_cls = SESSION_CLASSES[config["kind"]]
        session = session_cls(
            self.db, gid, uid, job_key, session_level, xp, last_work,
            dry_run=dry_run, buffs=buffs, difficulty=difficulty, ready_at=ready_at,
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
        self, interaction: discord.Interaction, job_key: str, config: dict,
        difficulty: str, buffs: dict | None,
    ) -> None:
        """The one-way door before .rob: get caught and infamy resets to
        0, so make sure the player actually meant to press the button."""
        gid, uid = interaction.guild_id, interaction.user.id
        tier = formulas.DIFFICULTIES[difficulty]
        panel = Panel(accent=Palette.RED, author_id=uid, timeout=30)
        panel.header(f"{config['title']} · Are You Sure?")
        panel.text(
            f"*{tier['emoji']} {tier['label']} difficulty. This isn't like the "
            "others. Get caught, and everything you've built goes up in "
            "smoke, your infamy resets to 0.*"
        )
        confirm_btn = ui.Button(label="Do It", emoji="🏦", style=discord.ButtonStyle.danger)
        cancel_btn = ui.Button(label="Walk Away", style=discord.ButtonStyle.secondary)

        async def on_confirm(inner: discord.Interaction) -> None:
            now = time.time()
            cooldown = apply_cooldown_buff(self._cooldown_for(job_key, config), buffs)
            last = await self.db.get_minigame_cooldown(gid, uid, job_key)
            if now < last + cooldown:
                await inner.response.edit_message(
                    view=simple_panel(
                        "Too late, the window's closed for now.", accent=Palette.RED
                    )
                )
                return
            await self.db.set_minigame_cooldown(gid, uid, job_key, now)
            skill = await self.db.get_skill(gid, uid, job_key)
            await self._send_session(
                InteractionSender(inner), gid, uid, job_key, config,
                skill["level"], skill["xp"], skill["last_work"],
                dry_run=False, buffs=buffs, difficulty=difficulty,
                ready_at=now + cooldown,
            )

        async def on_cancel(inner: discord.Interaction) -> None:
            await inner.response.edit_message(
                view=simple_panel(
                    "You think better of it and walk away.", accent=Palette.GOLD
                )
            )

        confirm_btn.callback = on_confirm
        cancel_btn.callback = on_cancel
        panel.buttons(confirm_btn, cancel_btn)
        await interaction.response.edit_message(view=panel)
        panel.message = interaction.message

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

    # ── tanner: stretch ─────────────────────────────────────────────────

    @commands.hybrid_command(
        name="stretch", description="Tanner minigame: spot the weak spot before the seam splits"
    )
    @commands.guild_only()
    async def stretch(self, ctx: commands.Context):
        await self._play(ctx, "tanner")

    @commands.hybrid_command(
        name="stretchtest", description="[Admin] Try the stretch minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Tanner level to simulate (default: 1)")
    async def stretchtest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "tanner", level=level, dry_run=True)

    # ── jeweler: facet ──────────────────────────────────────────────────

    @commands.hybrid_command(
        name="facet", description="Jeweler minigame: flip gems in pairs, one mismatch ends it"
    )
    @commands.guild_only()
    async def facet(self, ctx: commands.Context):
        await self._play(ctx, "jeweler")

    @commands.hybrid_command(
        name="facettest", description="[Admin] Try the facet minigame with no job/cooldown/rewards"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(level="Jeweler level to simulate (default: 1)")
    async def facettest(
        self, ctx: commands.Context, level: commands.Range[int, 1, formulas.MAX_LEVEL] = 1
    ):
        await self._play(ctx, "jeweler", level=level, dry_run=True)

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
