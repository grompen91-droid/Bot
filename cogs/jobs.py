"""Trades: the job board, choosing/quitting, working, and skills."""

from __future__ import annotations

import random
import time

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import captcha, formulas
from econ.data.crime import crime_tier
from econ.data.items import ITEMS, rarity_badge
from econ.data.jobs import JOBS, resolve_job
from econ.data.tools import tool_name
from ui.panels import (
    AMT_W,
    NAME_W,
    QTY_W,
    Palette,
    Panel,
    captcha_panel,
    chip,
    simple_panel,
)

JOB_CHOICES = [
    app_commands.Choice(name=f"{info['emoji']} {info['name']}", value=key)
    for key, info in JOBS.items()
]

# Skills that live in the same skills table but aren't tied to any
# trade in JOBS (currently just Crafting, see cogs/craft.py). .skills
# needs a display fallback for these or it silently skips the row.
NON_JOB_SKILL_DISPLAY = {
    "crafting": {"name": "Crafting", "emoji": "🛠️"},
}


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

        # The town guard's random anti-bot check.
        code = captcha.maybe_challenge(guild_id, member.id)
        if code:
            return captcha_panel(code)

        job_key = user["job"]
        info = JOBS[job_key]
        skill = await self.db.get_skill(guild_id, member.id, job_key)
        level = skill["level"]

        now = time.time()
        cooldown = formulas.effective_cooldown(info["cooldown"], level)
        ready_at = skill["last_work"] + cooldown
        if now < ready_at:
            return f"⏳ You are weary. You can work again <t:{int(ready_at)}:R>."

        if job_key == "criminal":
            return await self._build_criminal_work_panel(
                guild_id, member, skill, level, now
            )

        tier = await self.db.get_tool_tier(guild_id, member.id, job_key)
        total_before = await self.db.total_level(guild_id, member.id)
        # Item hauls scale with skill in THIS trade only; coin scales with
        # total skill across every trade, so gold stays hard to come by
        # early and grows with the breadth of what you've mastered.
        multiplier = formulas.total_multiplier(level, tier)
        coin_mult = formulas.coin_multiplier(total_before)

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

        tip = round(formulas.roll_tip(*info["tip"], level, tier) * coin_mult)
        xp_gain = formulas.roll_work_xp(info["cooldown"])

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
        panel.header(f"{info['emoji']} {info['name']}")
        if crit:
            panel.text("💥 **Critical work, double haul!**")
        else:
            panel.text(f"*{random.choice(info['flavour'])}*")

        haul_lines = []
        for item, qty in hauls:
            info_i = ITEMS[item]
            badge = rarity_badge(item).strip()
            haul_lines.append(
                f"{info_i['emoji']} "
                f"{chip((info_i['name'], NAME_W), (f'x{qty}', -QTY_W))}"
                + (f" {badge}" if badge else "")
            )
        if len(hauls) > 1:
            haul_lines[-1] += " *(bonus)*"
        haul_lines.append(
            f"💰 {chip(('Tip', NAME_W), (f'{tip:,}', -QTY_W))} 🪙"
        )
        panel.text("\n".join(haul_lines))

        if levels_gained:
            panel.text(
                f"⭐ **Level up!** {info['name']} is now level **{new_level}**"
            )
            newly_unlocked = self._newly_unlocked(
                total_before, total_before + levels_gained
            )
            for unlocked in newly_unlocked:
                panel.text(
                    f"🔓 The **{unlocked['emoji']} {unlocked['name']}** trade "
                    "is now open to you"
                )

        needed = formulas.xp_to_next(new_level)
        ready = int(now + formulas.effective_cooldown(info["cooldown"], new_level))
        panel.footer(
            f"+{xp_gain} XP · Lv {new_level} `{formulas.progress_bar(new_xp, needed)}` "
            f"{new_xp}/{needed}\nready <t:{ready}:R>"
        )

        work_btn = ui.Button(
            label="Work Again", emoji="⚒️", style=discord.ButtonStyle.secondary
        )
        work_btn.callback = self._work_again
        sell_btn = ui.Button(
            label="Sell Haul", emoji="🏪", style=discord.ButtonStyle.secondary
        )
        sell_btn.callback = self._make_sell_haul_handler(hauls)
        panel.buttons(work_btn, sell_btn)
        return panel

    async def _build_criminal_work_panel(
        self, guild_id: int, member: discord.abc.User, skill, level: int, now: float,
    ) -> Panel:
        """Criminal has no goods to gather, only gold and infamy. Both
        the payout and the flavour of the crime scale with how
        notorious you already are (see econ/data/crime.py)."""
        user = await self.db.get_user(guild_id, member.id)
        tier = await self.db.get_tool_tier(guild_id, member.id, "criminal")
        total_before = await self.db.total_level(guild_id, member.id)
        infamy = formulas.reputation_infamy(user["reputation"])

        gold = formulas.roll_criminal_work(level, tier, infamy, total_before)
        infamy_gain = random.randint(
            formulas.CRIMINAL_WORK_INFAMY_MIN, formulas.CRIMINAL_WORK_INFAMY_MAX
        )
        xp_gain = formulas.roll_work_xp(JOBS["criminal"]["cooldown"])

        new_level, new_xp, levels_gained = formulas.apply_xp(level, skill["xp"], xp_gain)
        await self.db.update_skill(guild_id, member.id, "criminal", new_level, new_xp, now)
        await self.db.add_gold(guild_id, member.id, gold)
        new_rep = await self.db.add_reputation(guild_id, member.id, -infamy_gain)
        new_infamy = formulas.reputation_infamy(new_rep)
        await self.db.incr_stat(guild_id, member.id, "works")
        await self.db.incr_stat(guild_id, member.id, "gold_from_crime", gold)

        _threshold, crime_title, flavour_lines = crime_tier(infamy)
        panel = Panel(accent=Palette.RED, author_id=member.id)
        panel.header(f"🗡️ Criminal · {crime_title}")
        panel.text(f"*{random.choice(flavour_lines)}*")
        panel.text(
            f"💰 {chip(('Take', NAME_W), (f'{gold:,}', -AMT_W))} 🪙\n"
            f"🗡️ {chip(('Infamy', NAME_W), (f'+{infamy_gain}', -AMT_W))} "
            f"({new_infamy:,} total)"
        )

        if levels_gained:
            panel.text(f"⭐ **Level up!** Criminal is now level **{new_level}**")

        needed = formulas.xp_to_next(new_level)
        ready = int(
            now + formulas.effective_cooldown(JOBS["criminal"]["cooldown"], new_level)
        )
        panel.footer(
            f"+{xp_gain} XP · Lv {new_level} `{formulas.progress_bar(new_xp, needed)}` "
            f"{new_xp}/{needed}\nready <t:{ready}:R>"
        )

        work_btn = ui.Button(
            label="Work Again", emoji="⚒️", style=discord.ButtonStyle.secondary
        )
        work_btn.callback = self._work_again
        panel.buttons(work_btn)
        return panel

    @staticmethod
    def _rarity(item_key: str) -> str:
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
        if getattr(result, "is_captcha", False):
            await interaction.response.send_message(view=result)
            return
        # A fresh message each time, not an edit-in-place, so every
        # work is its own entry in the channel history.
        await interaction.response.send_message(view=result)
        result.message = await interaction.original_response()

    def _make_sell_haul_handler(self, hauls: list[tuple[str, int]]):
        """Binds the Sell Haul button to exactly the items this one
        .work result produced, not the whole satchel."""
        async def handler(interaction: discord.Interaction) -> None:
            market = self.bot.get_cog("Market")
            result = await market.build_sell_items_panel(
                interaction.guild_id, interaction.user.id, hauls
            )
            if isinstance(result, str):
                await interaction.response.send_message(result, ephemeral=True)
                return
            await interaction.response.send_message(view=result)
        return handler

    # ══════════════════════════ job commands ═══════════════════════════

    @commands.hybrid_group(name="job", fallback="board", description="The town job board")
    @commands.guild_only()
    async def job(self, ctx: commands.Context):
        """Show the job board with a trade picker."""
        total = await self.db.total_level(ctx.guild.id, ctx.author.id)
        user = await self.db.get_user(ctx.guild.id, ctx.author.id)
        infamy = formulas.reputation_infamy(user["reputation"])

        criminal_jobs = [(k, i) for k, i in JOBS.items() if i["category"] == "criminal"]
        starters = [
            (k, i) for k, i in JOBS.items()
            if i["category"] == "guild" and i["unlock_total_level"] == 0
        ]
        guild_trades = sorted(
            (
                (k, i) for k, i in JOBS.items()
                if i["category"] == "guild" and i["unlock_total_level"] > 0
            ),
            key=lambda pair: pair[1]["unlock_total_level"],
        )

        panel = Panel(author_id=ctx.author.id)
        panel.header("🪧 The Town Job Board")
        panel.field(
            "Criminal",
            " · ".join(
                f"{i['emoji']} **{i['name']}**"
                + (" 📍" if user["job"] == k else "")
                for k, i in criminal_jobs
            ),
        )
        panel.field(
            "Starter",
            " · ".join(
                f"{i['emoji']} **{i['name']}**"
                + (" 📍" if user["job"] == k else "")
                for k, i in starters
            ),
        )
        guild_lines = []
        for key, i in guild_trades:
            req = i["unlock_total_level"]
            max_infamy = i["max_infamy"]
            too_infamous = max_infamy is not None and infamy > max_infamy
            if user["job"] == key:
                status = "📍"
            elif too_infamous:
                status = "🚫"
            elif total >= req:
                status = "✅"
            else:
                status = "🔒"
            name_field = f"{i['name']} ({req})"
            guild_lines.append(
                f"{i['emoji']} {chip((name_field, NAME_W))} {status}"
            )
        panel.field("Guild", "\n".join(guild_lines))
        if any(
            i["max_infamy"] is not None and infamy > i["max_infamy"]
            for _k, i in guild_trades
        ):
            panel.text("🚫 too infamous, the guild wants nothing to do with you")

        rank_emoji, rank_title = formulas.town_rank(total)
        footer = f"{rank_emoji} {rank_title} · Lv {total}"
        if user["job"]:
            footer = f"trade: {JOBS[user['job']]['name']} · " + footer
        if infamy:
            footer += f" · 🗡️ {infamy:,} infamy"
        panel.footer(footer)

        select = ui.Select(placeholder="⚒️ Take up a trade…")
        for key, info in JOBS.items():
            req = info["unlock_total_level"]
            max_infamy = info["max_infamy"]
            too_infamous = max_infamy is not None and infamy > max_infamy
            locked = total < req or too_infamous
            if too_infamous:
                description = f"Refuses anyone above {max_infamy} infamy"
            elif locked:
                description = f"Requires {req} total skill levels"
            else:
                description = info["description"][:100]
            select.add_option(
                label=info["name"],
                value=key,
                emoji="🚫" if too_infamous else ("🔒" if locked else info["emoji"]),
                description=description,
            )
        select.callback = self._board_select
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
        ready_at = user["last_job_switch"] + formulas.JOB_SWITCH_COOLDOWN
        if user["job"] and time.time() < ready_at:
            panel = simple_panel(
                "🏛️ The guild clerk shakes his head. You changed trades "
                f"only recently. Come back <t:{int(ready_at)}:R>.",
                accent=Palette.RED,
            )
            panel.accent_is_error = True
            return panel
        if total < info["unlock_total_level"]:
            panel = simple_panel(
                f"🔒 The {info['emoji']} **{info['name']}**'s guild turns you away. "
                f"They want **{info['unlock_total_level']} total skill levels** "
                f"and you have {total}. Master your current trade first!",
                accent=Palette.RED,
            )
            panel.accent_is_error = True
            return panel
        max_infamy = info["max_infamy"]
        infamy = formulas.reputation_infamy(user["reputation"])
        if max_infamy is not None and infamy > max_infamy:
            panel = simple_panel(
                f"🚫 The {info['emoji']} **{info['name']}**'s guild wants nothing "
                f"to do with someone of your reputation. They'll tolerate at "
                f"most **{max_infamy} infamy** and you have {infamy:,}.",
                accent=Palette.RED,
            )
            panel.accent_is_error = True
            return panel

        await self.db.set_job(guild_id, member.id, job_key, time.time())
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
        await self.db.set_job(ctx.guild.id, ctx.author.id, None, time.time())
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
        skill = await self.db.peek_skill(ctx.guild.id, ctx.author.id, job_key)
        tier = await self.db.get_tool_tier(ctx.guild.id, ctx.author.id, job_key)
        level = skill["level"]

        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header(f"{info['emoji']} {info['name']}")

        if info["yields"]:
            total_weight = sum(w for *_rest, w in info["yields"])
            yield_lines = []
            for item, lo, hi, w in info["yields"]:
                badge = rarity_badge(item).strip()
                yield_lines.append(
                    f"{ITEMS[item]['emoji']} "
                    f"{chip((ITEMS[item]['name'], NAME_W), (f'{lo}-{hi}', QTY_W), (f'{w / total_weight:.0%}', -AMT_W))}"
                    + (f" {badge}" if badge else "")
                )
            panel.text("\n".join(yield_lines))
        else:
            panel.text("*No goods, gold and infamy only. See* `.work`.")

        total = await self.db.total_level(ctx.guild.id, ctx.author.id)
        coin_mult = formulas.coin_multiplier(total)
        panel.footer(
            f"Lv {level} · {tool_name(job_key, tier)} · "
            f"yields ×{formulas.total_multiplier(level, tier):.2f} · "
            f"coin ×{coin_mult:.2f} · "
            f"{formulas.effective_cooldown(info['cooldown'], level):.0f}s cooldown"
        )
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
                info = JOBS.get(row["job"]) or NON_JOB_SKILL_DISPLAY.get(row["job"])
                if not info:
                    continue
                needed = formulas.xp_to_next(row["level"])
                lines.append(
                    f"{info['emoji']} **{info['name']}** Lv **{row['level']}**\n"
                    f"`{formulas.progress_bar(row['xp'], needed)}` "
                    f"{row['xp']}/{needed} XP"
                )
            panel.text("\n\n".join(lines))
        rank_emoji, rank_title = formulas.town_rank(total)
        panel.footer(f"{rank_emoji} {rank_title} · total skill level {total}")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Jobs(bot))
