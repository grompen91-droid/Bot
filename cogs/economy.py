"""Coin purse: balance, daily stipend, payments, profile, leaderboards."""

from __future__ import annotations

from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from econ import formulas
from econ.data.bank import MAX_BANK_TIER, bank_capacity, bank_upgrade_cost
from econ.data.jobs import JOBS
from econ.data.tools import tool_name
from ui.panels import AMT_W, NAME_W, WEALTH_W, Palette, Panel, chip, simple_panel


def _resolve_amount(text: str, available: int) -> int | None:
    """'all'/'max' -> available; a plain number -> that number; else None."""
    t = text.strip().lower().replace(",", "")
    if t in ("all", "max"):
        return available
    if t.isdigit():
        return int(t)
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
            f"🏦 Bank: **{bank:,}** / {cap:,} 🪙"
        )
        await ctx.send(view=panel)

    @commands.hybrid_command(name="daily", description="Collect your daily stipend from the town coffers")
    @commands.guild_only()
    async def daily(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        today = date.today()

        if user["last_daily"] == today.isoformat():
            await ctx.send(
                view=simple_panel(
                    "🕯️ The coffers open but once a day. Return on the morrow!",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        yesterday = (today - timedelta(days=1)).isoformat()
        streak = user["daily_streak"] + 1 if user["last_daily"] == yesterday else 1
        total_level = await self.db.total_level(gid, uid)
        payout, streak_bonus, level_bonus = formulas.daily_payout(streak, total_level)

        await self.db.set_daily(gid, uid, today.isoformat(), streak)
        balance = await self.db.add_gold(gid, uid, payout)

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
        panel.footer(f"Purse: {balance:,} gold")
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

    # ══════════════════════════════ bank ═══════════════════════════════

    @commands.hybrid_command(name="deposit", aliases=["dep"], description="Move gold from your pocket into the bank")
    @commands.guild_only()
    @app_commands.describe(amount="How much to deposit, or 'all'")
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
                view=simple_panel("Deposit a positive amount, or `all`.", accent=Palette.RED),
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
        await self.db.deposit_gold(gid, uid, amt)
        user = await self.db.get_user(gid, uid)
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏦 Deposited")
        panel.text(f"# {formulas.fmt_gold(amt)}")
        panel.footer(f"Pocket: {user['gold']:,} · Bank: {user['bank_gold']:,}/{cap:,} gold")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="withdraw", aliases=["with"], description="Take gold out of the bank")
    @commands.guild_only()
    @app_commands.describe(amount="How much to withdraw, or 'all'")
    async def withdraw(self, ctx: commands.Context, *, amount: str = "all"):
        gid, uid = ctx.guild.id, ctx.author.id
        user = await self.db.get_user(gid, uid)
        amt = _resolve_amount(amount, user["bank_gold"])
        if amt is None or amt <= 0:
            await ctx.send(
                view=simple_panel("Withdraw a positive amount, or `all`.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        if amt > user["bank_gold"]:
            await ctx.send(
                view=simple_panel("You don't have that much banked.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        await self.db.withdraw_gold(gid, uid, amt)
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
        if user["gold"] < cost:
            await interaction.response.send_message(
                view=simple_panel(
                    f"That upgrade costs {formulas.fmt_gold(cost)}, but you only "
                    f"have {formulas.fmt_gold(user['gold'])}.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        await self.db.add_gold(gid, uid, -cost)
        await self.db.set_bank_tier(gid, uid, tier + 1)
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🏦 Bank Upgraded!")
        panel.text(
            f"Capacity is now **{bank_capacity(tier + 1):,}** gold for "
            f"{formulas.fmt_gold(cost)}."
        )
        await interaction.response.send_message(view=panel)

    @commands.hybrid_command(name="profile", description="Your standing in the town")
    @commands.guild_only()
    @app_commands.describe(member="Whose profile to view (default: you)")
    async def profile(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        gid = ctx.guild.id
        user = await self.db.get_user(gid, target.id)
        total_level = await self.db.total_level(gid, target.id)

        if user["job"]:
            info = JOBS[user["job"]]
            skill = await self.db.get_skill(gid, target.id, user["job"])
            tier = await self.db.get_tool_tier(gid, target.id, user["job"])
            needed = formulas.xp_to_next(skill["level"])
            trade_lines = [
                f"{info['emoji']} **{info['name']}** Lv **{skill['level']}** · "
                f"🔧 {tool_name(user['job'], tier)}",
                f"`{formulas.progress_bar(skill['xp'], needed)}` "
                f"{skill['xp']}/{needed} XP",
            ]
        else:
            trade_lines = ["*No trade yet, see* `.job`"]

        rank_emoji, rank_title = formulas.town_rank(total_level)
        panel = Panel(timeout=None)
        panel.header(f"🏰 {target.display_name} of the Town")
        panel.section(
            f"{rank_emoji} **{rank_title}**",
            f"💰 **{formulas.fmt_gold(user['gold'])}**",
            thumbnail=target.display_avatar.url,
        )
        panel.text("\n".join(trade_lines))
        if user["daily_streak"]:
            panel.footer(f"🔥 {user['daily_streak']} day streak")
        await ctx.send(view=panel)

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
                name = self._display_name(ctx.guild, row["user_id"])
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
                name = self._display_name(ctx.guild, row["user_id"])
                lines.append(
                    f"{prefix} {chip((name, NAME_W), (f'{total:,}', -WEALTH_W))} 🪙"
                )
        panel = Panel(timeout=None)
        panel.header(title)
        panel.text("\n".join(lines) or "*The town ledger is empty.*")
        await ctx.send(view=panel)

    @staticmethod
    def _display_name(guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        return member.display_name if member else f"townsfolk {user_id}"


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
