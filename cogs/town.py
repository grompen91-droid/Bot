"""The mid-game settlement layer: found a personal town for a flat
500,000 gold, then grow it with gold + construction materials. See
econ/formulas.py's "the town" section for the cost/output math,
econ/town.py for the DB-aware glue, and econ/data/town_buildings.py /
town_workers.py / materials.py for the content itself.
"""

from __future__ import annotations

import time

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import formulas
from econ import town as town_lib
from econ.data.items import ITEMS, RARITIES
from econ.data.materials import (
    MATERIAL_GROUPS,
    MATERIAL_SUPPLY_BUNDLE,
    MATERIAL_SUPPLY_MARKUP,
    MATERIAL_SUPPLY_MAX_RARITY_ORDER,
)
from econ.data.town_buildings import (
    MAX_BUILDING_TIER,
    TOWN_BUILDINGS,
    building_tier_price,
    production_output_material,
    town_hall_material,
)
from econ.data.town_workers import MAX_WORKER_TIER, TOWN_WORKERS, worker_tier_price
from ui.panels import AMT_W, NAME_W, QTY_W, WEALTH_W, Palette, Panel, chip, simple_panel

EFFECT_LABELS = {
    "gold": "gold", "xp": "XP", "cooldown": "cooldown",
    "crit": "crit chance", "luck": "bonus-find chance", "defense": "crime defense",
}
GATHER_CHOICES = [
    app_commands.Choice(name=f"{info['emoji']} {info['name']}", value=key)
    for key, info in TOWN_BUILDINGS.items() if info["kind"] == "production"
]


def _resolve_production_building(query: str) -> str | None:
    """Fuzzy-match a production building by key or display name, same
    idea as cogs/market.py's resolve_item."""
    q = query.strip().lower().replace(" ", "_").replace("'", "")
    for key, info in TOWN_BUILDINGS.items():
        if info["kind"] != "production":
            continue
        if key == q or info["name"].lower().replace(" ", "_").replace("'", "") == q:
            return key
    return None


def _town_name(display_name: str) -> str:
    return f"{display_name} Town"


def _material_line(material: str, qty: int, owned: int) -> str:
    info = ITEMS[material]
    check = "✅" if owned >= qty else "❌"
    return f"{check} {info['emoji']} {info['name']} x{qty:,} *(have {owned:,})*"


def _building_effect_line(key: str, tier: int) -> str:
    """One line describing what a building tier gives, at that tier
    alone (not cumulative with any worker)."""
    info = TOWN_BUILDINGS[key]
    if info["kind"] == "production":
        rate = formulas.building_output_rate(info["base_rate"], tier, 0)
        cap = formulas.building_storage_cap(info["base_cap"], tier, 0)
        material = production_output_material(key, tier) if tier > 0 else None
        material_name = ITEMS[material]["name"] if material else "?"
        return f"+{rate:.1f} {material_name}/hr · cap {cap:.0f}"
    if info["effect"] == "worker_slots":
        return f"{formulas.worker_slots(tier)} worker slots"
    if info["effect"] == "storage_cap":
        return f"+{tier * formulas.STOREHOUSE_CAP_BONUS_PER_TIER * 100:.0f}% storage cap, every building"
    effect = info["effect"]
    sign = "-" if effect == "cooldown" else "+"
    pct = formulas.bonus_building_pct(effect, tier) * 100
    return f"{sign}{pct:.0f}% {EFFECT_LABELS[effect]}"


async def _try_pay(db, gid: int, uid: int, gold_cost: int, materials: dict[str, int]) -> bool:
    """Attempt to atomically spend gold + remove materials. Materials
    come off first (each remove_item is itself a conditional update),
    then gold; if any step fails, whatever was already removed is
    refunded so a purchase can't half-complete."""
    removed: list[tuple[str, int]] = []
    for mat, qty in materials.items():
        if not await db.remove_item(gid, uid, mat, qty):
            for m, q in removed:
                await db.add_item(gid, uid, m, q)
            return False
        removed.append((mat, qty))
    if not await db.spend_gold(gid, uid, gold_cost):
        for m, q in removed:
            await db.add_item(gid, uid, m, q)
        return False
    return True


class Town(commands.Cog):
    """Found and grow your own settlement."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ══════════════════════════ .townhall ══════════════════════════════

    async def _build_townhall_panel(self, gid: int, uid: int, display_name: str) -> Panel:
        town = await self.db.get_town(gid, uid)
        level = town["hall_level"]

        if level <= 0:
            panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=60)
            panel.header(f"🏰 Found {_town_name(display_name)}?")
            panel.text(
                f"Lay the foundation stone for **{formulas.fmt_gold(formulas.TOWN_HALL_FOUNDING_COST)}** "
                "and Town Hall rises to level 1 -- the one purchase that unlocks "
                "`.town`, `.buildings`, `.supply`, and everything built on top of them."
            )
            confirm_btn = ui.Button(label="Found the Town", emoji="🏰", style=discord.ButtonStyle.success)
            cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
            confirm_btn.callback = self._on_found_confirm
            cancel_btn.callback = self._on_generic_cancel
            panel.buttons(confirm_btn, cancel_btn)
            return panel

        panel = Panel(accent=Palette.IRON, author_id=uid, timeout=180)
        panel.header(f"🏰 {_town_name(display_name)} · Town Hall")
        lines = []
        for lvl in range(1, formulas.TOWN_HALL_MAX_LEVEL + 1):
            if lvl <= level:
                lines.append(f"✅ {chip((f'Level {lvl}', NAME_W), ('built', -WEALTH_W))}")
                continue
            gold, qty = formulas.town_hall_upgrade_cost(lvl)
            icon = "🏗️" if lvl == level + 1 else "🔒"
            lines.append(f"{icon} {chip((f'Level {lvl}', NAME_W), (f'{gold:,}', -WEALTH_W))} 🪙")
        panel.text("\n".join(lines))
        panel.footer(f"{level}/{formulas.TOWN_HALL_MAX_LEVEL} levels built")

        if level < formulas.TOWN_HALL_MAX_LEVEL:
            btn = ui.Button(label=f"Upgrade to Level {level + 1}", emoji="🏗️", style=discord.ButtonStyle.primary)
            btn.callback = self._on_hall_upgrade_button
            panel.buttons(btn)
        return panel

    @commands.hybrid_command(name="townhall", description="Found your town (500k gold), or upgrade Town Hall")
    @commands.guild_only()
    async def townhall(self, ctx: commands.Context):
        panel = await self._build_townhall_panel(ctx.guild.id, ctx.author.id, ctx.author.display_name)
        panel.message = await ctx.send(view=panel)

    async def _on_generic_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            view=simple_panel("You decide against it, for now.", accent=Palette.GOLD)
        )

    async def _on_found_confirm(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        town = await self.db.get_town(gid, uid)
        if town["hall_level"] > 0:
            await interaction.response.edit_message(
                view=simple_panel("Your town is already founded.", accent=Palette.RED)
            )
            return
        if not await self.db.spend_gold(gid, uid, formulas.TOWN_HALL_FOUNDING_COST):
            user = await self.db.get_user(gid, uid)
            await interaction.response.edit_message(
                view=simple_panel(
                    f"Founding a town costs {formulas.fmt_gold(formulas.TOWN_HALL_FOUNDING_COST)}, "
                    f"but your purse holds only {formulas.fmt_gold(user['gold'])}.",
                    accent=Palette.RED,
                )
            )
            return
        await self.db.found_town(gid, uid, time.time())
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header(f"🏰 {_town_name(interaction.user.display_name)} is Founded!")
        panel.text(
            "Town Hall stands at **level 1**. `.buildings` to start building, "
            "`.supply` to stock up on materials, `.town` for the overview."
        )
        await interaction.response.edit_message(view=panel)

    async def _on_hall_upgrade_button(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        town = await self.db.get_town(gid, uid)
        level = town["hall_level"]
        if level <= 0 or level >= formulas.TOWN_HALL_MAX_LEVEL:
            await interaction.response.edit_message(
                view=simple_panel("Nothing to upgrade right now.", accent=Palette.RED)
            )
            return
        next_level = level + 1
        gold_cost, qty = formulas.town_hall_upgrade_cost(next_level)
        material = town_hall_material(next_level)
        owned = await self.db.get_item_qty(gid, uid, material)
        user = await self.db.get_user(gid, uid)

        panel = Panel(accent=Palette.IRON, author_id=uid, timeout=60)
        panel.header(f"🏰 Upgrade Town Hall to Level {next_level}?")
        panel.text(
            f"{formulas.fmt_gold(gold_cost)} · {_material_line(material, qty, owned)}\n"
            f"Your purse: {user['gold']:,} gold"
        )
        confirm_btn = ui.Button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._on_hall_upgrade_confirm
        cancel_btn.callback = self._on_generic_cancel
        panel.buttons(confirm_btn, cancel_btn)
        await interaction.response.edit_message(view=panel)

    async def _on_hall_upgrade_confirm(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        town = await self.db.get_town(gid, uid)
        level = town["hall_level"]
        if level <= 0 or level >= formulas.TOWN_HALL_MAX_LEVEL:
            await interaction.response.edit_message(
                view=simple_panel("Nothing to upgrade right now.", accent=Palette.RED)
            )
            return
        next_level = level + 1
        gold_cost, qty = formulas.town_hall_upgrade_cost(next_level)
        material = town_hall_material(next_level)
        if not await _try_pay(self.db, gid, uid, gold_cost, {material: qty}):
            await interaction.response.edit_message(
                view=simple_panel(
                    "Not enough gold and materials for that upgrade yet.", accent=Palette.RED
                )
            )
            return
        await self.db.set_hall_level(gid, uid, next_level)
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header(f"🏰 Town Hall is now Level {next_level}!")
        panel.text("Check `.buildings` -- new construction may have just unlocked.")
        await interaction.response.edit_message(view=panel)

    # ══════════════════════════════ .town ══════════════════════════════

    async def _build_town_panel(self, gid: int, uid: int, display_name: str) -> Panel | None:
        town = await self.db.get_town(gid, uid)
        if town["hall_level"] <= 0:
            return None
        level = town["hall_level"]
        building_tiers = await town_lib.get_building_tiers(self.db, gid, uid)
        worker_tiers = await town_lib.get_worker_tiers(self.db, gid, uid)
        now = time.time()

        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"🏰 {_town_name(display_name)}")
        panel.text(
            f"Town Hall **Level {level}**/{formulas.TOWN_HALL_MAX_LEVEL} · "
            f"🏗️ {len(building_tiers)}/{len(TOWN_BUILDINGS)} buildings · "
            f"👷 {len(worker_tiers)}/{len(TOWN_WORKERS)} workers hired"
        )

        pending_lines = []
        total_pending = 0
        for key, tier in building_tiers.items():
            if TOWN_BUILDINGS[key]["kind"] != "production" or tier <= 0:
                continue
            qty = await town_lib.collectible_amount(self.db, gid, uid, key, now)
            if qty <= 0:
                continue
            material = production_output_material(key, tier)
            pending_lines.append(f"{ITEMS[material]['emoji']} {chip((ITEMS[material]['name'], NAME_W), (f'+{qty:,}', -QTY_W))}")
            total_pending += qty
        if pending_lines:
            panel.divider()
            panel.subheader("📦 Ready to Collect")
            panel.text("\n".join(pending_lines))
        else:
            panel.divider()
            panel.text("*Nothing waiting to collect right now.*")

        totals = await town_lib.town_bonus_totals(self.db, gid, uid)
        if totals:
            bonus_lines = []
            for effect, value in totals.items():
                sign = "-" if effect == "cooldown" else "+"
                bonus_lines.append(f"{sign}{value * 100:.0f}% {EFFECT_LABELS[effect]}")
            panel.divider()
            panel.subheader("✨ Town Bonuses")
            panel.text(" · ".join(bonus_lines))

        panel.footer("`.buildings` to build/upgrade · `.workers` to hire · `.supply` for materials")
        if total_pending > 0:
            collect_btn = ui.Button(label="Collect All", emoji="📦", style=discord.ButtonStyle.success)
            collect_btn.callback = self._on_collect_button
            panel.buttons(collect_btn)
        return panel

    @commands.hybrid_command(name="town", description="Your town: overview, bonuses, and pending collection")
    @commands.guild_only()
    async def town(self, ctx: commands.Context):
        panel = await self._build_town_panel(ctx.guild.id, ctx.author.id, ctx.author.display_name)
        if panel is None:
            await ctx.send(
                view=simple_panel(
                    "You haven't founded a town yet. Run `.townhall` "
                    f"({formulas.fmt_gold(formulas.TOWN_HALL_FOUNDING_COST)}) to start one.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        panel.message = await ctx.send(view=panel)

    async def _on_collect_button(self, interaction: discord.Interaction) -> None:
        result = await self._do_collect(interaction.guild_id, interaction.user.id)
        await interaction.response.edit_message(view=result)

    async def _do_collect(self, gid: int, uid: int) -> Panel:
        collected = await town_lib.collect_all(self.db, gid, uid, time.time())
        if not collected:
            return simple_panel("Nothing was ready to collect.", accent=Palette.RED)
        lines = [
            f"{ITEMS[m]['emoji']} {chip((ITEMS[m]['name'], NAME_W), (f'+{q:,}', -QTY_W))}"
            for m, q in collected.items()
        ]
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("📦 Collected!")
        panel.text("\n".join(lines))
        panel.footer("Straight into your satchel.")
        return panel

    @commands.hybrid_command(name="collect", description="Collect what your production buildings have made")
    @commands.guild_only()
    async def collect(self, ctx: commands.Context):
        town = await self.db.get_town(ctx.guild.id, ctx.author.id)
        if town["hall_level"] <= 0:
            await ctx.send(
                view=simple_panel("You haven't founded a town yet. Run `.townhall`.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        panel = await self._do_collect(ctx.guild.id, ctx.author.id)
        await ctx.send(view=panel)

    # ══════════════════════════════ .gather ══════════════════════════════
    # The active counterpart to .collect's idle trickle: a short per-
    # building cooldown you have to actually spend a command on, paying
    # out a batch of that building's CURRENT material plus a chance at
    # ONE unit of the NEXT tier's -- the only way to bridge to a tier
    # whose material .supply doesn't sell and nothing yet produces.

    @commands.hybrid_command(
        name="gather",
        description="Actively gather materials from one of your built production buildings",
    )
    @commands.guild_only()
    @app_commands.describe(building="Which production building to gather from")
    @app_commands.choices(building=GATHER_CHOICES)
    async def gather(self, ctx: commands.Context, *, building: str):
        gid, uid = ctx.guild.id, ctx.author.id
        key = _resolve_production_building(building)
        if key is None:
            await ctx.send(
                view=simple_panel(f"No such production building: **{building}**.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        info = TOWN_BUILDINGS[key]
        tier = await self.db.get_building_tier(gid, uid, key)
        if tier <= 0:
            await ctx.send(
                view=simple_panel(f"Build a **{info['name']}** first (see `.buildings`).", accent=Palette.RED),
                ephemeral=True,
            )
            return

        cooldown_key = f"gather_{key}"
        last = await self.db.get_minigame_cooldown(gid, uid, cooldown_key)
        now = time.time()
        if now < last + formulas.GATHER_COOLDOWN:
            await ctx.send(
                view=simple_panel(
                    f"The {info['name']} needs more time before it can be worked again. "
                    f"Ready <t:{int(last + formulas.GATHER_COOLDOWN)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        total_level = await self.db.total_level(gid, uid)
        qty = formulas.gather_yield(tier, total_level)
        material = production_output_material(key, tier)
        await self.db.add_item(gid, uid, material, qty)
        await self.db.set_minigame_cooldown(gid, uid, cooldown_key, now)

        bonus_line = None
        if tier < MAX_BUILDING_TIER and formulas.roll_gather_bridge():
            next_material = production_output_material(key, tier + 1)
            await self.db.add_item(gid, uid, next_material, 1)
            next_info = ITEMS[next_material]
            bonus_line = f"✨ A rare find: **1x {next_info['emoji']} {next_info['name']}**!"

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header(f"{info['emoji']} Gathered from the {info['name']}!")
        mat_info = ITEMS[material]
        panel.text(f"{mat_info['emoji']} {chip((mat_info['name'], NAME_W), (f'+{qty}', -QTY_W))}")
        if bonus_line:
            panel.text(bonus_line)
        panel.footer(f"Ready again <t:{int(now + formulas.GATHER_COOLDOWN)}:R>")
        await ctx.send(view=panel)

    # ══════════════════════════════ .buildings ═══════════════════════════

    async def _build_buildings_panel(self, gid: int, uid: int, display_name: str) -> Panel | None:
        town = await self.db.get_town(gid, uid)
        if town["hall_level"] <= 0:
            return None
        hall_level = town["hall_level"]
        building_tiers = await town_lib.get_building_tiers(self.db, gid, uid)
        user = await self.db.get_user(gid, uid)

        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"🏗️ {_town_name(display_name)} · Buildings")

        select = ui.Select(placeholder="🏗️ Build or upgrade…")
        lines = []
        for key, info in TOWN_BUILDINGS.items():
            tier = building_tiers.get(key, 0)
            emoji, name = info["emoji"], info["name"]
            if hall_level < info["unlock_hall_level"] and tier <= 0:
                unlock_lvl = info["unlock_hall_level"]
                lines.append(
                    f"🔒 {chip((name, NAME_W), (f'hall lvl {unlock_lvl}', -13))}"
                )
                continue
            if tier >= MAX_BUILDING_TIER:
                lines.append(f"✅ {chip((name, NAME_W), ('maxed', -WEALTH_W))} · {_building_effect_line(key, tier)}")
                continue
            next_tier = tier + 1
            gold_cost, materials = building_tier_price(key, next_tier)
            lines.append(
                f"{emoji if tier > 0 else '🏗️'} {chip((name, NAME_W), (f'Tier {tier}->{next_tier}', -13))} "
                f"· {gold_cost:,} 🪙 · {_building_effect_line(key, next_tier)}"
            )
            select.add_option(
                label=f"{name} (Tier {tier} -> {next_tier})"[:100],
                value=key,
                emoji=emoji,
                description=f"{gold_cost:,} gold + materials"[:100],
            )
        panel.text("\n".join(lines))
        panel.footer(f"Town Hall Level {hall_level} · Your purse: {user['gold']:,} gold")
        if select.options:
            select.callback = self._on_building_select
            panel.select(select)
        return panel

    @commands.hybrid_command(name="buildings", description="Build or upgrade your town's buildings")
    @commands.guild_only()
    async def buildings(self, ctx: commands.Context):
        panel = await self._build_buildings_panel(ctx.guild.id, ctx.author.id, ctx.author.display_name)
        if panel is None:
            await ctx.send(
                view=simple_panel("Found your town first with `.townhall`.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        panel.message = await ctx.send(view=panel)

    async def _on_building_select(self, interaction: discord.Interaction) -> None:
        key = interaction.data["values"][0]
        gid, uid = interaction.guild_id, interaction.user.id
        town = await self.db.get_town(gid, uid)
        tier = await self.db.get_building_tier(gid, uid, key)
        info = TOWN_BUILDINGS[key]
        if tier <= 0 and town["hall_level"] < info["unlock_hall_level"]:
            await interaction.response.edit_message(
                view=simple_panel(
                    f"**{info['name']}** needs Town Hall level {info['unlock_hall_level']}.",
                    accent=Palette.RED,
                )
            )
            return
        if tier >= MAX_BUILDING_TIER:
            await interaction.response.edit_message(
                view=simple_panel(f"**{info['name']}** is already fully built.", accent=Palette.RED)
            )
            return
        next_tier = tier + 1
        gold_cost, materials = building_tier_price(key, next_tier)
        user = await self.db.get_user(gid, uid)
        mat_lines = []
        for mat, qty in materials.items():
            owned = await self.db.get_item_qty(gid, uid, mat)
            mat_lines.append(_material_line(mat, qty, owned))

        verb = "Build" if tier == 0 else "Upgrade"
        panel = Panel(accent=Palette.IRON, author_id=uid, timeout=60)
        panel.header(f"{info['emoji']} {verb} {info['name']} to Tier {next_tier}?")
        panel.text(
            f"{info['flavor']}\n\n{formulas.fmt_gold(gold_cost)}\n" + "\n".join(mat_lines) +
            f"\n\nWill give: **{_building_effect_line(key, next_tier)}**\n"
            f"Your purse: {user['gold']:,} gold"
        )
        confirm_btn = ui.Button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._make_building_confirm_handler(key, next_tier)
        cancel_btn.callback = self._on_generic_cancel
        panel.buttons(confirm_btn, cancel_btn)
        await interaction.response.edit_message(view=panel)

    def _make_building_confirm_handler(self, key: str, next_tier: int):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            current = await self.db.get_building_tier(gid, uid, key)
            if current != next_tier - 1:
                await interaction.response.edit_message(
                    view=simple_panel("That building has already changed. Run `.buildings` again.", accent=Palette.RED)
                )
                return
            gold_cost, materials = building_tier_price(key, next_tier)
            if not await _try_pay(self.db, gid, uid, gold_cost, materials):
                await interaction.response.edit_message(
                    view=simple_panel("Not enough gold and materials for that yet.", accent=Palette.RED)
                )
                return
            now = time.time()
            if next_tier == 1:
                await self.db.set_building_tier(gid, uid, key, 1, last_collected=now)
            else:
                await self.db.set_building_tier(gid, uid, key, next_tier)
            info = TOWN_BUILDINGS[key]
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header(f"{info['emoji']} {info['name']} is now Tier {next_tier}!")
            panel.text(f"**{_building_effect_line(key, next_tier)}**")
            await interaction.response.edit_message(view=panel)
        return handler

    # ══════════════════════════════ .workers ═════════════════════════════

    async def _build_workers_panel(self, gid: int, uid: int, display_name: str) -> Panel | str | None:
        town = await self.db.get_town(gid, uid)
        if town["hall_level"] <= 0:
            return None
        lodge_tier = await self.db.get_building_tier(gid, uid, "workers_lodge")
        if lodge_tier <= 0:
            return "no_lodge"

        worker_tiers = await town_lib.get_worker_tiers(self.db, gid, uid)
        used, capacity = await town_lib.hired_worker_slots_used(self.db, gid, uid)
        user = await self.db.get_user(gid, uid)

        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"👷 {_town_name(display_name)} · Workers")
        panel.text(f"Hire slots: **{used}/{capacity}** (raise this by upgrading the Workers' Lodge)")

        select = ui.Select(placeholder="👷 Hire or upgrade…")
        lines = []
        for key, info in TOWN_WORKERS.items():
            tier = worker_tiers.get(key, 0)
            building = TOWN_BUILDINGS[info["linked"]]
            if tier >= MAX_WORKER_TIER:
                lines.append(f"✅ {chip((info['name'], NAME_W), ('maxed', -WEALTH_W))} · {building['name']}")
                continue
            if tier <= 0 and used >= capacity:
                lines.append(f"🔒 {chip((info['name'], NAME_W), ('no slots', -WEALTH_W))} · {building['name']}")
                continue
            next_tier = tier + 1
            gold_cost, materials = worker_tier_price(key, next_tier)
            lines.append(
                f"{info['emoji']} {chip((info['name'], NAME_W), (f'Tier {tier}->{next_tier}', -13))} "
                f"· {gold_cost:,} 🪙 · boosts {building['name']}"
            )
            select.add_option(
                label=f"{info['name']} (Tier {tier} -> {next_tier})"[:100],
                value=key,
                emoji=info["emoji"],
                description=f"{gold_cost:,} gold + materials · boosts {building['name']}"[:100],
            )
        panel.text("\n".join(lines))
        panel.footer(f"Your purse: {user['gold']:,} gold")
        if select.options:
            select.callback = self._on_worker_select
            panel.select(select)
        return panel

    @commands.hybrid_command(name="workers", description="Hire and upgrade townsfolk to work your buildings")
    @commands.guild_only()
    async def workers(self, ctx: commands.Context):
        panel = await self._build_workers_panel(ctx.guild.id, ctx.author.id, ctx.author.display_name)
        if panel is None:
            await ctx.send(
                view=simple_panel("Found your town first with `.townhall`.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        if panel == "no_lodge":
            await ctx.send(
                view=simple_panel(
                    "Build a **Workers' Lodge** first (see `.buildings`) before you can hire anyone.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        panel.message = await ctx.send(view=panel)

    async def _on_worker_select(self, interaction: discord.Interaction) -> None:
        key = interaction.data["values"][0]
        gid, uid = interaction.guild_id, interaction.user.id
        info = TOWN_WORKERS[key]
        tier = await self.db.get_worker_tier(gid, uid, key)
        used, capacity = await town_lib.hired_worker_slots_used(self.db, gid, uid)
        if tier <= 0 and used >= capacity:
            await interaction.response.edit_message(
                view=simple_panel("No free hire slots. Upgrade your Workers' Lodge first.", accent=Palette.RED)
            )
            return
        if tier >= MAX_WORKER_TIER:
            await interaction.response.edit_message(
                view=simple_panel(f"**{info['name']}** is already fully trained.", accent=Palette.RED)
            )
            return
        next_tier = tier + 1
        gold_cost, materials = worker_tier_price(key, next_tier)
        user = await self.db.get_user(gid, uid)
        mat_lines = []
        for mat, qty in materials.items():
            owned = await self.db.get_item_qty(gid, uid, mat)
            mat_lines.append(_material_line(mat, qty, owned))

        verb = "Hire" if tier == 0 else "Train"
        building = TOWN_BUILDINGS[info["linked"]]
        panel = Panel(accent=Palette.IRON, author_id=uid, timeout=60)
        panel.header(f"{info['emoji']} {verb} {info['name']} to Tier {next_tier}?")
        panel.text(
            f"{info['flavor']}\nBoosts **{building['name']}**.\n\n"
            f"{formulas.fmt_gold(gold_cost)}\n" + "\n".join(mat_lines) +
            f"\n\nYour purse: {user['gold']:,} gold"
        )
        confirm_btn = ui.Button(label="Confirm", emoji="✅", style=discord.ButtonStyle.success)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        confirm_btn.callback = self._make_worker_confirm_handler(key, next_tier)
        cancel_btn.callback = self._on_generic_cancel
        panel.buttons(confirm_btn, cancel_btn)
        await interaction.response.edit_message(view=panel)

    def _make_worker_confirm_handler(self, key: str, next_tier: int):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            current = await self.db.get_worker_tier(gid, uid, key)
            if current != next_tier - 1:
                await interaction.response.edit_message(
                    view=simple_panel("That worker has already changed. Run `.workers` again.", accent=Palette.RED)
                )
                return
            if current <= 0:
                used, capacity = await town_lib.hired_worker_slots_used(self.db, gid, uid)
                if used >= capacity:
                    await interaction.response.edit_message(
                        view=simple_panel("No free hire slots anymore.", accent=Palette.RED)
                    )
                    return
            gold_cost, materials = worker_tier_price(key, next_tier)
            if not await _try_pay(self.db, gid, uid, gold_cost, materials):
                await interaction.response.edit_message(
                    view=simple_panel("Not enough gold and materials for that yet.", accent=Palette.RED)
                )
                return
            await self.db.set_worker_tier(gid, uid, key, next_tier)
            info = TOWN_WORKERS[key]
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header(f"{info['emoji']} {info['name']} is now Tier {next_tier}!")
            panel.text(f"Boosting **{TOWN_BUILDINGS[info['linked']]['name']}**.")
            await interaction.response.edit_message(view=panel)
        return handler

    # ══════════════════════════════ .supply ══════════════════════════════
    # Builder's Supply: flat-markup, always-in-stock (no daily rotation
    # unlike .shop), sold in bundles since building/worker tiers need
    # materials by the dozen. Only bootstraps the CHEAP end though --
    # common/uncommon materials, so a fresh building can get off the
    # ground. Rare and above can't be bought at any price: they come
    # from a production building's own trickle once it's already there,
    # from `.gather`, or a lucky drop from ordinary `.work` (the
    # "universal" group only). See MATERIAL_SUPPLY_MAX_RARITY_ORDER.

    @staticmethod
    def _rarity_order(key: str) -> int:
        return list(RARITIES.keys()).index(ITEMS[key]["rarity"])

    def _supply_categories(self) -> list[tuple[str, str, str, list[str]]]:
        cats = []
        for key, items in MATERIAL_GROUPS.items():
            if key == "universal":
                continue
            info = TOWN_BUILDINGS[key]
            cats.append((key, info["emoji"], info["name"], items))
        cats.append(("universal", "🧰", "Universal", MATERIAL_GROUPS["universal"]))
        return cats

    async def _build_supply_panel(self, gid: int, uid: int, category_key: str) -> Panel:
        cats = self._supply_categories()
        by_key = {key: (emoji, name, items) for key, emoji, name, items in cats}
        emoji, name, item_keys = by_key[category_key]
        user = await self.db.get_user(gid, uid)

        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"🧱 Builder's Supply · {emoji} {name}")
        panel.text(
            f"*Sold in bundles of {MATERIAL_SUPPLY_BUNDLE}, always in stock, no daily rotation -- "
            "common and uncommon only. Rarer stock has to be earned, not bought.*"
        )

        lines = []
        select = ui.Select(placeholder="🧱 Buy a bundle…")
        for key in item_keys:
            info = ITEMS[key]
            owned = await self.db.get_item_qty(gid, uid, key)
            if self._rarity_order(key) > MATERIAL_SUPPLY_MAX_RARITY_ORDER:
                lines.append(
                    f"🔒 {chip((info['name'], NAME_W), (f'x{owned}', QTY_W), ('earn it', -13))}"
                )
                continue
            price = round(info["value"] * MATERIAL_SUPPLY_MARKUP * MATERIAL_SUPPLY_BUNDLE)
            lines.append(
                f"{info['emoji']} {chip((info['name'], NAME_W), (f'x{owned}', QTY_W), (f'{price:,}', -AMT_W))} 🪙"
            )
            select.add_option(
                label=f"{info['name']} x{MATERIAL_SUPPLY_BUNDLE} · {price:,}g"[:100],
                value=key,
                emoji=info["emoji"],
            )
        panel.text("\n".join(lines))
        if category_key != "universal":
            info = TOWN_BUILDINGS[category_key]
            panel.footer(
                f"Your purse: {user['gold']:,} gold · rarer {info['name']} stock: "
                f"`.gather {category_key}` or its own trickle once built"
            )
        else:
            panel.footer(f"Your purse: {user['gold']:,} gold · rarer stock: a lucky find from `.work`")

        cat_select = ui.Select(placeholder="🧱 Browse a group…")
        for key, e, n, _items in cats:
            cat_select.add_option(label=n, value=key, emoji=e, default=(key == category_key))
        cat_select.callback = self._supply_category_select
        panel.select(cat_select)

        select.callback = self._supply_buy_select
        panel.select(select)
        return panel

    @commands.hybrid_command(name="supply", aliases=["builderssupply"], description="Buy construction materials for your town")
    @commands.guild_only()
    async def supply(self, ctx: commands.Context):
        town = await self.db.get_town(ctx.guild.id, ctx.author.id)
        if town["hall_level"] <= 0:
            await ctx.send(
                view=simple_panel("Found your town first with `.townhall`.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        default_key = self._supply_categories()[0][0]
        panel = await self._build_supply_panel(ctx.guild.id, ctx.author.id, default_key)
        panel.message = await ctx.send(view=panel)

    async def _supply_category_select(self, interaction: discord.Interaction) -> None:
        category_key = interaction.data["values"][0]
        panel = await self._build_supply_panel(interaction.guild_id, interaction.user.id, category_key)
        panel.message = interaction.message
        await interaction.response.edit_message(view=panel)

    async def _supply_buy_select(self, interaction: discord.Interaction) -> None:
        item_key = interaction.data["values"][0]
        gid, uid = interaction.guild_id, interaction.user.id
        info = ITEMS[item_key]
        price = round(info["value"] * MATERIAL_SUPPLY_MARKUP * MATERIAL_SUPPLY_BUNDLE)
        if not await self.db.spend_gold(gid, uid, price):
            user = await self.db.get_user(gid, uid)
            await interaction.response.edit_message(
                view=simple_panel(
                    f"That bundle costs {formulas.fmt_gold(price)}, but your purse "
                    f"holds only {formulas.fmt_gold(user['gold'])}.",
                    accent=Palette.RED,
                )
            )
            return
        await self.db.add_item(gid, uid, item_key, MATERIAL_SUPPLY_BUNDLE)
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🧱 Purchased!")
        panel.text(f"{info['emoji']} {chip((info['name'], NAME_W), (f'+{MATERIAL_SUPPLY_BUNDLE}', -QTY_W))} for {formulas.fmt_gold(price)}")
        await interaction.response.edit_message(view=panel)

    # ══════════════════════════════ .study ═══════════════════════════════
    # A material/gold sink once production outpaces what buildings need:
    # spend some to inject XP straight into one trade. Gated behind the
    # Great Library.

    STUDY_MATERIAL_COST = {"blueprint_scroll": 5, "arcane_blueprint": 2}

    @commands.hybrid_command(name="study", description="Spend gold and materials for an instant XP boost (needs a Great Library)")
    @commands.guild_only()
    @app_commands.describe(trade="Which trade's skill to boost (or 'crafting')")
    async def study(self, ctx: commands.Context, *, trade: str):
        from cogs.jobs import resolve_skill_key
        gid, uid = ctx.guild.id, ctx.author.id
        library_tier = await self.db.get_building_tier(gid, uid, "great_library")
        if library_tier <= 0:
            await ctx.send(
                view=simple_panel("Build a **Great Library** first (see `.buildings`).", accent=Palette.RED),
                ephemeral=True,
            )
            return
        job_key = resolve_skill_key(trade)
        if job_key is None:
            await ctx.send(
                view=simple_panel(f"No such trade: **{trade}**.", accent=Palette.RED), ephemeral=True,
            )
            return
        last = await self.db.get_minigame_cooldown(gid, uid, "study")
        now = time.time()
        if now < last + formulas.STUDY_COOLDOWN:
            await ctx.send(
                view=simple_panel(f"You need more to study. Ready <t:{int(last + formulas.STUDY_COOLDOWN)}:R>.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        if not await _try_pay(self.db, gid, uid, formulas.STUDY_GOLD_COST, self.STUDY_MATERIAL_COST):
            mats = ", ".join(f"{q}x {ITEMS[m]['name']}" for m, q in self.STUDY_MATERIAL_COST.items())
            await ctx.send(
                view=simple_panel(
                    f"Studying costs {formulas.fmt_gold(formulas.STUDY_GOLD_COST)} + {mats}.", accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        await self.db.set_minigame_cooldown(gid, uid, "study", now)
        xp_gain = formulas.STUDY_XP_PER_LIBRARY_TIER * library_tier
        skill = await self.db.get_skill(gid, uid, job_key)
        curve = formulas.craft_xp_to_next if job_key == "crafting" else formulas.xp_to_next
        new_level, new_xp, levels_gained = formulas.apply_xp(
            skill["level"], skill["xp"], xp_gain, curve=curve
        )
        await self.db.update_skill(gid, uid, job_key, new_level, new_xp, skill["last_work"])

        panel = Panel(accent=Palette.PURPLE, timeout=None)
        panel.header("📚 A Long Night of Study")
        panel.text(f"**+{xp_gain:,} XP** poured straight into your training.")
        if levels_gained:
            panel.text(f"⭐ **Level up!** Now level **{new_level}**.")
        await ctx.send(view=panel)

    # ══════════════════════════════ .patrol ═══════════════════════════════

    @commands.hybrid_command(name="patrol", description="Walk the walls for a small payout (needs a Watchtower)")
    @commands.guild_only()
    async def patrol(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        watchtower_tier = await self.db.get_building_tier(gid, uid, "watchtower")
        if watchtower_tier <= 0:
            await ctx.send(
                view=simple_panel("Build a **Watchtower** first (see `.buildings`).", accent=Palette.RED),
                ephemeral=True,
            )
            return
        last = await self.db.get_minigame_cooldown(gid, uid, "patrol")
        now = time.time()
        if now < last + formulas.PATROL_COOLDOWN:
            await ctx.send(
                view=simple_panel(f"Still on watch. Ready <t:{int(last + formulas.PATROL_COOLDOWN)}:R>.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        guard_captain_tier = await self.db.get_worker_tier(gid, uid, "guard_captain")
        gold = round(2_000 * (1 + 0.3 * watchtower_tier + 0.2 * guard_captain_tier))
        await self.db.set_minigame_cooldown(gid, uid, "patrol", now)
        await self.db.add_gold(gid, uid, gold)
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header("🗼 Patrol Complete")
        panel.text(f"You catch a smuggler slipping past the gate and confiscate **{formulas.fmt_gold(gold)}**.")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Town(bot))
