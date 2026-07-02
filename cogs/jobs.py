"""Trades: the job board, choosing/quitting, working, and skills."""

from __future__ import annotations

import random
import time

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import formulas
from econ.data.items import item_label, rarity_badge
from econ.data.jobs import JOBS, resolve_job
from econ.data.tools import tool_name
from ui.panels import Palette, Panel, simple_panel

JOB_CHOICES = [
    app_commands.Choice(name=f"{info['emoji']} {info['name']}", value=key)
    for key, info in JOBS.items()
]


class Jobs(commands.Cog):
    """Everything about earning your keep."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ══════════════════════════ work engine ════════════════════════════
    # Shared by the .work command and the ⚒️ Work Again button.

    async def build_work_panel(
        self, guild_id: int, member: discord.abc.User
    ) -> Panel | str:
        """Run one unit of work. Returns a result Panel, or an error string
        (to be sent ephemerally / as a short notice)."""
        user = await self.db.get_user(guild_id, member.id)
        if not user["job"]:
            return (
                "🪧 You have no trade! Visit the job board with `.job` "
                "and take one up with `.job choose <trade>`."
            )

        job_key = user["job"]
        info = JOBS[job_key]
        skill = await self.db.get_skill(guild_id, member.id, job_key)
        level = skill["level"]

        now = time.time()
        cooldown = formulas.effective_cooldown(info["cooldown"], level)
        ready_at = skill["last_work"] + cooldown
        if now < ready_at:
            return f"⏳ You are weary. You can work again <t:{int(ready_at)}:R>."

        tier = await self.db.get_tool_tier(guild_id, member.id, job_key)
        multiplier = formulas.total_multiplier(level, tier)

        # Primary haul: one weighted roll, with luck favouring rare+ finds.
        entries = info["yields"]
        weights = [
            formulas.effective_weight(w, self._rarity(item), level)
            for item, _lo, _hi, w in entries
        ]
        hauls = [self._roll_haul(entries, weights, multiplier)]

        # A skilled worker sometimes finds something extra.
        if random.random() < formulas.bonus_find_chance(level):
            hauls.append(
                self._roll_haul(
                    entries, weights, multiplier * formulas.BONUS_FIND_YIELD_FACTOR
                )
            )

        # Critical work doubles everything.
        crit = random.random() < formulas.crit_chance(level, tier)
        if crit:
            hauls = [
                (item, round(qty * formulas.CRIT_MULTIPLIER)) for item, qty in hauls
            ]

        tip = formulas.roll_tip(*info["tip"], level, tier)
        xp_gain = formulas.roll_work_xp(info["cooldown"])
        total_before = await self.db.total_level(guild_id, member.id)

        new_level, new_xp, levels_gained = formulas.apply_xp(
            level, skill["xp"], xp_gain
        )
        await self.db.update_skill(
            guild_id, member.id, job_key, new_level, new_xp, now
        )
        for item, qty in hauls:
            await self.db.add_item(guild_id, member.id, item, qty)
            await self.db.incr_stat(guild_id, member.id, "items_gathered", qty)
        await self.db.add_gold(guild_id, member.id, tip)
        await self.db.incr_stat(guild_id, member.id, "works")
        await self.db.incr_stat(guild_id, member.id, "gold_from_tips", tip)

        # ── build the result panel ──────────────────────────────────────
        accent = Palette.PURPLE if crit else Palette.GOLD
        panel = Panel(accent=accent, author_id=member.id)
        panel.header(f"{info['emoji']} {info['name']} at Work")
        panel.text(f"*{random.choice(info['flavour'])}*")
        if crit:
            panel.text("💥 **A masterful day's work — double haul!**")
        panel.divider()

        haul_lines = [
            f"{rarity_badge(item)} {item_label(item)} × **{qty}**"
            for item, qty in hauls
        ]
        if len(hauls) > 1:
            haul_lines[-1] += "  *(lucky bonus find!)*"
        haul_lines.append(f"💰 Tip: **{formulas.fmt_gold(tip)}**")
        panel.field("Your haul", "\n".join(haul_lines))

        if levels_gained:
            panel.divider()
            panel.text(
                f"⭐ **Level up!** Your {info['name']} skill is now level "
                f"**{new_level}** *(yields ×{formulas.total_multiplier(new_level, tier):.2f})*"
            )
            newly_unlocked = self._newly_unlocked(
                total_before, total_before + levels_gained
            )
            for unlocked in newly_unlocked:
                panel.text(
                    f"🔓 The **{unlocked['emoji']} {unlocked['name']}** trade "
                    "is now open to you! *(`.job choose`)*"
                )

        needed = formulas.xp_to_next(new_level)
        ready = int(now + formulas.effective_cooldown(info["cooldown"], new_level))
        panel.footer(
            f"+{xp_gain} XP · Lv. {new_level} "
            f"`{formulas.progress_bar(new_xp, needed)}` {new_xp}/{needed} · "
            f"🔧 {tool_name(job_key, tier)} · rested <t:{ready}:R>"
        )

        work_btn = ui.Button(
            label="Work Again", emoji="⚒️", style=discord.ButtonStyle.secondary
        )
        work_btn.callback = self._work_again
        sell_hint = ui.Button(
            label="Sell with .sell", emoji="🏪",
            style=discord.ButtonStyle.grey, disabled=True,
        )
        panel.divider()
        panel.buttons(work_btn, sell_hint)
        return panel

    @staticmethod
    def _rarity(item_key: str) -> str:
        from econ.data.items import ITEMS

        return ITEMS[item_key]["rarity"]

    @staticmethod
    def _roll_haul(entries, weights, multiplier: float) -> tuple[str, int]:
        item, lo, hi, _w = random.choices(entries, weights=weights, k=1)[0]
        qty = max(1, round(random.randint(lo, hi) * multiplier))
        return item, qty

    @staticmethod
    def _newly_unlocked(total_before: int, total_after: int) -> list[dict]:
        return [
            info
            for info in JOBS.values()
            if total_before < info["unlock_total_level"] <= total_after
        ]

    async def _work_again(self, interaction: discord.Interaction) -> None:
        result = await self.build_work_panel(interaction.guild_id, interaction.user)
        if isinstance(result, str):
            await interaction.response.send_message(result, ephemeral=True)
            return
        result.message = interaction.message
        await interaction.response.edit_message(view=result)

    # ══════════════════════════ job commands ═══════════════════════════

    @commands.hybrid_group(name="job", fallback="board", description="The town job board")
    @commands.guild_only()
    async def job(self, ctx: commands.Context):
        """Show the job board with a trade picker."""
        total = await self.db.total_level(ctx.guild.id, ctx.author.id)
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)

        panel = Panel(author_id=ctx.author.id)
        panel.header("🪧 The Town Job Board")
        panel.text(
            "Take up a trade and earn your keep with `.work`. Switch whenever "
            "you like — **your skills are never forgotten.**"
        )
        panel.divider()

        lines = []
        for key, info in JOBS.items():
            req = info["unlock_total_level"]
            lock = "" if total >= req else f" 🔒 *needs {req} total levels*"
            current = " ← *your trade*" if user["job"] == key else ""
            lines.append(
                f"{info['emoji']} **{info['name']}** — {info['description']}"
                f"{lock}{current}"
            )
        panel.text("\n".join(lines))
        panel.footer(
            f"Your total skill level: {total} · pick below or use .job choose <trade>"
        )

        select = ui.Select(placeholder="⚒️ Take up a trade…")
        for key, info in JOBS.items():
            req = info["unlock_total_level"]
            locked = total < req
            select.add_option(
                label=info["name"],
                value=key,
                emoji="🔒" if locked else info["emoji"],
                description=(
                    f"Requires {req} total skill levels"
                    if locked
                    else info["description"][:100]
                ),
            )
        select.callback = self._board_select
        panel.divider()
        panel.select(select)
        panel.message = await ctx.send(view=panel)

    async def _board_select(self, interaction: discord.Interaction) -> None:
        job_key = interaction.data["values"][0]
        panel = await self._choose_job(
            interaction.guild_id, interaction.user, job_key
        )
        await interaction.response.send_message(
            view=panel, ephemeral=isinstance(panel, Panel) and panel.accent_is_error
        )

    async def _choose_job(
        self, guild_id: int, member: discord.abc.User, job_key: str
    ) -> Panel:
        info = JOBS[job_key]
        user = await self.db.get_user(guild_id, member.id)
        total = await self.db.total_level(guild_id, member.id)

        if user["job"] == job_key:
            panel = simple_panel(
                f"You already work as a {info['emoji']} **{info['name']}**.",
                accent=Palette.RED,
            )
            panel.accent_is_error = True
            return panel
        if total < info["unlock_total_level"]:
            panel = simple_panel(
                f"🔒 The {info['emoji']} **{info['name']}**'s guild turns you away — "
                f"they want **{info['unlock_total_level']} total skill levels** "
                f"(you have {total}). Master your current trade first!",
                accent=Palette.RED,
            )
            panel.accent_is_error = True
            return panel

        await self.db.set_job(guild_id, member.id, job_key)
        skill = await self.db.get_skill(guild_id, member.id, job_key)
        tier = await self.db.get_tool_tier(guild_id, member.id, job_key)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.accent_is_error = False
        panel.header(f"{info['emoji']} A new {info['name']} joins the town!")
        panel.text(
            f"{member.mention} takes up the {info['name'].lower()}'s trade at "
            f"skill level **{skill['level']}** with a trusty "
            f"**{tool_name(job_key, tier)}**."
        )
        panel.footer("Work with .work · view progress with .skills")
        return panel

    @job.command(name="choose", description="Take up a trade")
    @app_commands.describe(trade="The trade you wish to practise")
    @app_commands.choices(trade=JOB_CHOICES)
    async def job_choose(self, ctx: commands.Context, *, trade: str):
        job_key = resolve_job(trade)
        if job_key is None:
            await ctx.send(
                view=simple_panel(
                    f"No guild in town knows the trade **{trade}**. "
                    "See the board with `.job`.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        panel = await self._choose_job(ctx.guild.id, ctx.author, job_key)
        await ctx.send(view=panel, ephemeral=panel.accent_is_error)

    @job.command(name="quit", description="Lay down your tools and quit your trade")
    async def job_quit(self, ctx: commands.Context):
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        if not user["job"]:
            await ctx.send(
                view=simple_panel("You have no trade to quit.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        info = JOBS[user["job"]]
        await self.db.set_job(ctx.guild.id, ctx.author.id, None)
        await ctx.send(
            view=simple_panel(
                f"You hang up your tools as a {info['emoji']} **{info['name']}**. "
                "Your skill is remembered should you ever return.",
            )
        )

    @job.command(name="info", description="Learn what a trade yields")
    @app_commands.describe(trade="The trade to inspect")
    @app_commands.choices(trade=JOB_CHOICES)
    async def job_info(self, ctx: commands.Context, *, trade: str):
        job_key = resolve_job(trade)
        if job_key is None:
            await ctx.send(
                view=simple_panel(f"No such trade: **{trade}**.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        info = JOBS[job_key]
        skill = await self.db.get_skill(ctx.guild.id, ctx.author.id, job_key)
        tier = await self.db.get_tool_tier(ctx.guild.id, ctx.author.id, job_key)
        level = skill["level"]

        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header(f"{info['emoji']} The {info['name']}'s Trade")
        panel.text(f"*{info['description']}*")
        panel.divider()

        total_weight = sum(w for *_rest, w in info["yields"])
        yield_lines = [
            f"{rarity_badge(item)} {item_label(item)} — {lo}–{hi} "
            f"*({w / total_weight:.0%})*"
            for item, lo, hi, w in info["yields"]
        ]
        panel.field("Possible hauls", "\n".join(yield_lines))
        panel.divider()
        panel.field(
            "Your standing",
            f"Skill: **Lv. {level}** · Tool: **{tool_name(job_key, tier)}**\n"
            f"Yields ×{formulas.total_multiplier(level, tier):.2f} · "
            f"work every {formulas.effective_cooldown(info['cooldown'], level):.0f}s · "
            f"crit {formulas.crit_chance(level, tier):.0%} · "
            f"bonus find {formulas.bonus_find_chance(level):.0%}",
        )
        panel.footer(f"tip {info['tip'][0]}–{info['tip'][1]} gold per work, before bonuses")
        await ctx.send(view=panel)

    # ══════════════════════════════ work ═══════════════════════════════

    @commands.hybrid_command(name="work", description="Labour at your trade for goods and coin")
    @commands.guild_only()
    async def work(self, ctx: commands.Context):
        result = await self.build_work_panel(ctx.guild.id, ctx.author)
        if isinstance(result, str):
            await ctx.send(view=simple_panel(result, accent=Palette.RED), ephemeral=True)
            return
        result.message = await ctx.send(view=result)

    @commands.hybrid_command(name="skills", description="Skill levels in every trade")
    @commands.guild_only()
    @app_commands.describe(member="Whose skills to inspect (default: you)")
    async def skills(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        rows = await self.db.get_all_skills(ctx.guild.id, target.id)
        total = await self.db.total_level(ctx.guild.id, target.id)

        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header(f"📖 Skills of {target.display_name}")
        if not rows:
            panel.text("*No trades practised yet. Visit the job board with `.job`!*")
        else:
            lines = []
            for row in rows:
                info = JOBS.get(row["job"])
                if not info:
                    continue
                needed = formulas.xp_to_next(row["level"])
                lines.append(
                    f"{info['emoji']} **{info['name']}** — Lv. **{row['level']}**\n"
                    f"`{formulas.progress_bar(row['xp'], needed)}` "
                    f"{row['xp']}/{needed} XP"
                )
            panel.text("\n\n".join(lines))
        panel.footer(f"Total skill level: {total}")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Jobs(bot))
