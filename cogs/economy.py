"""Coin purse: balance, daily stipend, payments, profile, leaderboards."""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timedelta, timezone

import discord
from discord import app_commands, ui
from discord.ext import commands

from cogs.jobs import NON_JOB_SKILL_DISPLAY
from econ import formulas
from econ.buffs import active_buff_summary, active_buff_totals, apply_cooldown_buff, apply_gold_buff
from econ.data.bank import MAX_BANK_TIER, bank_capacity, bank_upgrade_cost
from econ.data.jobs import JOBS
from econ.data.themes import DEFAULT_THEME, THEMES, resolve_theme
from ui.panels import AMT_W, NAME_W, WEALTH_W, Palette, Panel, chip, simple_panel
from ui.profile_card import ProfileCardData, render_profile_card

GRANTABLE_THEME_CHOICES = [
    app_commands.Choice(name=f"{t['emoji']} {t['name']}", value=key)
    for key, t in THEMES.items() if key != DEFAULT_THEME
]


def _resolve_amount(text: str, available: int) -> int | None:
    """'all'/'max' -> available; 'half' -> half of it; a plain number,
    optionally with a k/m suffix ('10k', '1.5m'), -> that number;
    anything else -> None."""
    t = text.strip().lower().replace(",", "")
    if t in ("all", "max"):
        return available
    if t == "half":
        return available // 2
    multiplier = 1
    if t.endswith("k"):
        multiplier, t = 1_000, t[:-1]
    elif t.endswith("m"):
        multiplier, t = 1_000_000, t[:-1]
    try:
        return int(float(t) * multiplier)
    except (ValueError, OverflowError):
        return None


class Economy(commands.Cog):
    """Gold in, gold out."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(name="balance", aliases=["bal", "gold"], description="Count the coin in a purse")
    @commands.guild_only()
    @app_commands.describe(member="Whose purse to peek at (default: you)")
    async def balance(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        user = await self.db.get_user(ctx.guild.id, target.id)
        pocket, bank = user["gold"], user["bank_gold"]
        cap = bank_capacity(user["bank_tier"])
        panel = Panel(timeout=None)
        panel.header(f"💰 {target.display_name}'s Purse")
        panel.text(
            f"👛 {chip(('Pocket', NAME_W), (f'{pocket:,}', -WEALTH_W))} 🪙\n"
            f"🏦 {chip(('Bank', NAME_W), (f'{bank:,}', -WEALTH_W))} 🪙\n"
            f"💰 {chip(('Total', NAME_W), (f'{pocket + bank:,}', -WEALTH_W))} 🪙"
        )
        panel.footer(f"bank capacity {cap:,} gold · leaderboard ranks by total")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="daily", description="Collect your daily stipend from the town coffers")
    @commands.guild_only()
    async def daily(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        # UTC day, same clock the market uses, so the daily rolls over at
        # the same moment no matter where the bot is hosted.
        today = datetime.now(timezone.utc).date()

        if user["last_daily"] == today.isoformat():
            reset_at = datetime.combine(
                today + timedelta(days=1), dtime.min, tzinfo=timezone.utc
            )
            await ctx.send(
                view=simple_panel(
                    "🕯️ The coffers open but once a day. You can collect "
                    f"again <t:{int(reset_at.timestamp())}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        yesterday = (today - timedelta(days=1)).isoformat()
        streak = user["daily_streak"] + 1 if user["last_daily"] == yesterday else 1
        total_level = await self.db.total_level(gid, uid)
        payout, streak_bonus, level_bonus = formulas.daily_payout(streak, total_level)
        buffs = await active_buff_totals(self.db, gid, uid)
        payout = round(apply_gold_buff(payout, buffs))

        await self.db.set_daily(gid, uid, today.isoformat(), streak)
        balance = await self.db.add_gold(gid, uid, payout)
        await self.db.incr_stat(gid, uid, "gold_from_daily", payout)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏛️ Daily Stipend")
        panel.text(f"# {formulas.fmt_gold(payout)}")
        extras = []
        if streak_bonus:
            extras.append(f"🔥 streak ×{streak}: +{streak_bonus:,}")
        if level_bonus:
            extras.append(f"📖 skill: +{level_bonus:,}")
        if extras:
            panel.text(" · ".join(extras))
        footer = f"Purse: {balance:,} gold"
        buff_line = active_buff_summary(buffs)
        if buff_line:
            footer += f"\n✨ active: {buff_line}"
        panel.footer(footer)
        await ctx.send(view=panel)

    @commands.hybrid_command(name="beg", description="Beg passersby for a few coins")
    @commands.guild_only()
    async def beg(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)

        buffs = await active_buff_totals(self.db, gid, uid)
        now = time.time()
        last = await self.db.get_minigame_cooldown(gid, uid, "beg")
        ready_at = last + apply_cooldown_buff(formulas.BEG_COOLDOWN, buffs)
        if now < ready_at:
            await ctx.send(
                view=simple_panel(
                    f"🥺 Folk are getting tired of you. Ready <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        await self.db.set_minigame_cooldown(gid, uid, "beg", now)
        gold, rep_delta = formulas.roll_beg(user["reputation"])
        gold = round(apply_gold_buff(gold, buffs))
        balance = await self.db.add_gold(gid, uid, gold)
        await self.db.incr_stat(gid, uid, "gold_from_begging", gold)
        if rep_delta:
            await self.db.add_reputation(gid, uid, rep_delta)

        panel = Panel(accent=Palette.GOLD, timeout=None)
        panel.header("🥺 A Few Coins")
        panel.text(f"A passing townsfolk takes pity and tosses you **{gold:,} 🪙**.")
        footer = f"Purse: {balance:,} gold"
        if rep_delta:
            footer += f" · 🌟 {rep_delta} fame (a little beneath you)"
        buff_line = active_buff_summary(buffs)
        if buff_line:
            footer += f"\n✨ active: {buff_line}"
        panel.footer(footer)
        await ctx.send(view=panel)

    @commands.hybrid_command(name="pay", description="Hand coin to another townsfolk")
    @commands.guild_only()
    @app_commands.describe(member="Who receives the coin", amount="How much gold to give")
    async def pay(
        self,
        ctx: commands.Context,
        member: discord.Member,
        amount: commands.Range[int, 1],
    ):
        if member.bot or member.id == ctx.author.id:
            await ctx.send(
                view=simple_panel(
                    "You cannot pay yourself, nor a construct of gears and magic.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        ok = await self.db.transfer_gold(ctx.guild.id, ctx.author.id, member.id, amount)
        if not ok:
            await ctx.send(
                view=simple_panel("Your purse is too light for that.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        await self.db.incr_stat(ctx.guild.id, ctx.author.id, "gold_gifted", amount)
        await ctx.send(
            view=simple_panel(
                f"🤝 {ctx.author.mention} hands **{formulas.fmt_gold(amount)}** "
                f"to {member.mention}.",
                accent=Palette.GREEN,
            )
        )

    @commands.hybrid_command(
        name="deduct", description="[Admin] Remove gold from a townsfolk's pocket purse"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        member="Whose purse to dock", amount="How much gold to remove"
    )
    async def deduct(
        self,
        ctx: commands.Context,
        member: discord.Member,
        amount: commands.Range[int, 1],
    ):
        gid = ctx.guild.id
        # Unlike every player-facing gold sink, an admin's deduction isn't
        # clamped to what's in the purse -- it can push a balance into the
        # negative, e.g. as a debt/penalty a player has to work off.
        new_balance = await self.db.add_gold(gid, member.id, -amount)
        await ctx.send(
            view=simple_panel(
                f"🛡️ Docked **{formulas.fmt_gold(amount)}** from {member.mention}'s "
                f"purse. They now carry **{formulas.fmt_gold(new_balance)}**.",
                accent=Palette.BLUE,
            )
        )

    # ══════════════════════════════ bank ═══════════════════════════════

    @commands.hybrid_command(name="deposit", aliases=["dep"], description="Move gold from your pocket into the bank")
    @commands.guild_only()
    @app_commands.describe(amount="How much to deposit: a number, '10k', 'half', or 'all'")
    async def deposit(self, ctx: commands.Context, *, amount: str = "all"):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        cap = bank_capacity(user["bank_tier"])
        room = cap - user["bank_gold"]
        if room <= 0:
            await ctx.send(
                view=simple_panel(
                    "🏦 Your bank is already full. Upgrade it with `.bank`.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        amt = _resolve_amount(amount, min(user["gold"], room))
        if amt is None or amt <= 0:
            await ctx.send(
                view=simple_panel(
                    "Deposit a positive amount, `half`, or `all`.", accent=Palette.RED
                ),
                ephemeral=True,
            )
            return
        if amt > user["gold"]:
            await ctx.send(
                view=simple_panel("You don't have that much on hand.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        if amt > room:
            await ctx.send(
                view=simple_panel(
                    f"🏦 Your bank only has room for **{room:,}** more gold.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        ok = await self.db.deposit_gold(gid, uid, amt, cap)
        if not ok:
            await ctx.send(
                view=simple_panel(
                    "🏦 The clerk recounts your coin and shakes his head, "
                    "your purse or vault changed while you queued. Try again.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        user = await self.db.get_user(gid, uid)
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏦 Deposited")
        panel.text(f"# {formulas.fmt_gold(amt)}")
        panel.footer(f"Pocket: {user['gold']:,} · Bank: {user['bank_gold']:,}/{cap:,} gold")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="withdraw", aliases=["with"], description="Take gold out of the bank")
    @commands.guild_only()
    @app_commands.describe(amount="How much to withdraw: a number, '10k', 'half', or 'all'")
    async def withdraw(self, ctx: commands.Context, *, amount: str = "all"):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        amt = _resolve_amount(amount, user["bank_gold"])
        if amt is None or amt <= 0:
            await ctx.send(
                view=simple_panel(
                    "Withdraw a positive amount, `half`, or `all`.", accent=Palette.RED
                ),
                ephemeral=True,
            )
            return
        ok = await self.db.withdraw_gold(gid, uid, amt)
        if not ok:
            await ctx.send(
                view=simple_panel("You don't have that much banked.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        user = await self.db.get_user(gid, uid)
        cap = bank_capacity(user["bank_tier"])
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏦 Withdrawn")
        panel.text(f"# {formulas.fmt_gold(amt)}")
        panel.footer(f"Pocket: {user['gold']:,} · Bank: {user['bank_gold']:,}/{cap:,} gold")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="bank", description="The bank: your balance and capacity upgrades")
    @commands.guild_only()
    async def bank(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        tier = user["bank_tier"]
        cap = bank_capacity(tier)

        panel = Panel(accent=Palette.IRON, author_id=uid)
        panel.header("🏦 The Bank")
        panel.text(f"Balance: **{user['bank_gold']:,}** / {cap:,} 🪙")
        lines = []
        for t in range(MAX_BANK_TIER + 1):
            cap_label = f"{bank_capacity(t):,} cap"
            if t <= tier:
                lines.append(f"✅ {chip((cap_label, NAME_W), ('owned', -WEALTH_W))}")
            else:
                icon = "🏦" if t == tier + 1 else "🔒"
                cost = bank_upgrade_cost(t)
                lines.append(f"{icon} {chip((cap_label, NAME_W), (f'{cost:,}', -WEALTH_W))} 🪙")
        panel.text("\n".join(lines))
        panel.footer(f"Your purse: {user['gold']:,} gold")

        if tier < MAX_BANK_TIER:
            cost = bank_upgrade_cost(tier + 1)
            btn = discord.ui.Button(
                label=f"Upgrade to {bank_capacity(tier + 1):,} cap · {cost:,} gold",
                emoji="🏦",
                style=discord.ButtonStyle.primary,
            )
            btn.callback = self._upgrade_bank
            panel.buttons(btn)
        panel.message = await ctx.send(view=panel)

    async def _upgrade_bank(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        user = await self.db.get_user(gid, uid)
        tier = user["bank_tier"]
        if tier >= MAX_BANK_TIER:
            await interaction.response.send_message(
                view=simple_panel("Your bank is already at its finest.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        cost = bank_upgrade_cost(tier + 1)
        if not await self.db.spend_gold(gid, uid, cost):
            await interaction.response.send_message(
                view=simple_panel(
                    f"That upgrade costs {formulas.fmt_gold(cost)}, but you only "
                    f"have {formulas.fmt_gold(user['gold'])}.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        await self.db.set_bank_tier(gid, uid, tier + 1)
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏦 Bank Upgraded!")
        panel.text(
            f"Capacity is now **{bank_capacity(tier + 1):,}** gold for "
            f"{formulas.fmt_gold(cost)}."
        )
        await interaction.response.send_message(view=panel)

    @commands.hybrid_command(name="profile", description="Your standing in the town, as a card")
    @commands.guild_only()
    @app_commands.describe(member="Whose profile to view (default: you)")
    async def profile(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        gid = ctx.guild.id
        user = await self.db.get_user(gid, target.id)
        total_level = await self.db.total_level(gid, target.id)

        skills = await self.db.get_all_skills(gid, target.id)
        if skills:
            best = max(skills, key=lambda row: row["level"])
            info = JOBS.get(best["job"]) or NON_JOB_SKILL_DISPLAY.get(best["job"])
            best_trade_label = f"{info['name']} Lv {best['level']}" if info else "No trade yet"
        else:
            best_trade_label = "No trade yet"

        gold_rank = await self.db.gold_rank(gid, target.id)
        skill_rank = await self.db.skill_rank(gid, target.id)
        _rank_emoji, rank_title = formulas.town_rank(total_level)
        theme = THEMES.get(user["theme"], THEMES[DEFAULT_THEME])

        reputation = user["reputation"]
        if reputation < 0:
            rep_label, rep_value = "Infamy", f"{formulas.reputation_infamy(reputation):,}"
        elif reputation > 0:
            rep_label, rep_value = "Fame", f"{formulas.reputation_fame(reputation):,}"
        else:
            rep_label, rep_value = "Standing", "Neutral"

        try:
            avatar_bytes = await target.display_avatar.replace(size=256).read()
        except Exception:
            # A card missing its avatar (a placeholder circle instead)
            # beats the whole command failing over a flaky CDN fetch.
            avatar_bytes = None

        card = render_profile_card(ProfileCardData(
            display_name=target.display_name,
            avatar_bytes=avatar_bytes,
            accent_rgb=theme["accent"].to_rgb(),
            layout=theme["layout"],
            rank_title=rank_title,
            flair=theme["flair"],
            level=total_level,
            pocket_gold=user["gold"],
            bank_gold=user["bank_gold"],
            best_trade_label=best_trade_label,
            gold_rank=gold_rank,
            skill_rank=skill_rank,
            reputation_label=rep_label,
            reputation_value=rep_value,
        ))
        await ctx.send(file=discord.File(card, filename="profile.png"))

    @commands.hybrid_command(
        name="theme", aliases=["themes"],
        description="View and equip your unlocked cosmetic profile themes",
    )
    @commands.guild_only()
    async def theme(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        equipped = user["theme"]
        if equipped not in THEMES:
            # Whatever they had equipped no longer exists in the
            # registry (e.g. a theme that's since been retired) -- fall
            # back to the default and heal the row so this doesn't have
            # to happen again next time.
            equipped = DEFAULT_THEME
            await self.db.set_theme(gid, uid, DEFAULT_THEME)
        unlocked = {DEFAULT_THEME} | set(await self.db.get_unlocked_themes(gid, uid))

        panel = Panel(accent=THEMES[equipped]["accent"], author_id=uid, timeout=120)
        panel.header("🎨 Profile Themes")
        lines = []
        for key, t in THEMES.items():
            if key == equipped:
                mark = "✅"
            elif key in unlocked:
                mark = "🔓"
            else:
                mark = "🔒"
            lines.append(f"{mark} {t['emoji']} **{t['name']}** -- {t['description']}")
        panel.text("\n".join(lines))
        panel.footer("Purely cosmetic, no gameplay effect · unlocked themes are admin-granted")

        select = ui.Select(placeholder="🎨 Equip a theme…")
        for key in THEMES:
            if key not in unlocked:
                continue
            t = THEMES[key]
            select.add_option(
                label=t["name"], value=key, emoji=t["emoji"], default=(key == equipped)
            )
        select.callback = self._equip_theme
        panel.select(select)
        await ctx.send(view=panel)

    async def _equip_theme(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        key = interaction.data["values"][0]
        unlocked = {DEFAULT_THEME} | set(await self.db.get_unlocked_themes(gid, uid))
        if key not in unlocked:
            await interaction.response.edit_message(
                view=simple_panel("You don't own that theme.", accent=Palette.RED)
            )
            return
        await self.db.set_theme(gid, uid, key)
        t = THEMES[key]
        await interaction.response.edit_message(
            view=simple_panel(
                f"{t['emoji']} Equipped **{t['name']}**. Check it out with `.profile`.",
                accent=t["accent"],
            )
        )

    @commands.hybrid_command(
        name="granttheme", description="[Admin] Unlock a cosmetic profile theme for a townsfolk"
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="Who receives the theme", theme="Which theme to unlock")
    @app_commands.choices(theme=GRANTABLE_THEME_CHOICES)
    async def granttheme(
        self, ctx: commands.Context, member: discord.Member, *, theme: str
    ):
        key = resolve_theme(theme)
        if key is None or key == DEFAULT_THEME:
            await ctx.send(
                view=simple_panel(f"No such theme: **{theme}**.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        gid = ctx.guild.id
        await self.db.unlock_theme(gid, member.id, key)
        t = THEMES[key]
        await ctx.send(
            view=simple_panel(
                f"🎁 Unlocked {t['emoji']} **{t['name']}** for {member.mention}. "
                "They can equip it with `.theme`.",
                accent=t["accent"],
            )
        )

    @commands.hybrid_command(name="leaderboard", aliases=["lb", "top"], description="The wealthiest and most skilled in town")
    @commands.guild_only()
    @app_commands.describe(board="Which ranking to view")
    @app_commands.choices(
        board=[
            app_commands.Choice(name="💰 Richest townsfolk", value="gold"),
            app_commands.Choice(name="📖 Most skilled", value="skills"),
        ]
    )
    async def leaderboard(self, ctx: commands.Context, board: str = "gold"):
        gid = ctx.guild.id
        medals = ["🥇", "🥈", "🥉"]
        if board.lower().startswith("skill"):
            rows = await self.db.top_skills(gid)
            title = "📖 The Most Skilled Townsfolk"
            lines = []
            for i, row in enumerate(rows):
                total = row["total_level"]
                emoji, _title = formulas.town_rank(total)
                prefix = medals[i] if i < 3 else f"{i + 1}."
                name = await self._display_name(ctx.guild, row["user_id"])
                lines.append(
                    f"{prefix} {chip((name, NAME_W), (f'{total:,}', -AMT_W))} {emoji}"
                )
        else:
            rows = await self.db.top_gold(gid)
            title = "💰 The Richest Townsfolk"
            lines = []
            for i, row in enumerate(rows):
                total = row["total_gold"]
                prefix = medals[i] if i < 3 else f"{i + 1}."
                name = await self._display_name(ctx.guild, row["user_id"])
                lines.append(
                    f"{prefix} {chip((name, NAME_W), (f'{total:,}', -WEALTH_W))} 🪙"
                )
        panel = Panel(timeout=None)
        panel.header(title)
        panel.text("\n".join(lines) or "*The town ledger is empty.*")
        await ctx.send(view=panel)

    @staticmethod
    async def _display_name(guild: discord.Guild, user_id: int) -> str:
        """The member cache only holds whoever the bot has recently seen
        (no members intent), so a leaderboard entry for someone quiet is
        a cache miss, not someone who left -- fetch before giving up."""
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                return f"townsfolk {user_id}"
        return member.display_name


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
