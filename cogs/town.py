"""The mid-game settlement layer: found a personal town for a flat
150,000 gold, then grow it with gold + construction materials. See
econ/formulas.py's "the town" section for the cost/output math,
econ/town.py for the DB-aware glue, and econ/data/town_buildings.py /
town_workers.py / materials.py for the content itself.
"""

from __future__ import annotations

import random
import time

import discord
from discord import app_commands, ui
from discord.ext import commands

from econ import formulas
from econ import town as town_lib
from econ.buffs import active_buff_totals, apply_cooldown_buff, apply_gold_buff
from econ.data.caravans import CARAVAN_ROUTE_ORDER, CARAVAN_ROUTES
from econ.data.expeditions import (
    EXPEDITION_CHOICE_ORDER,
    EXPEDITION_CHOICES,
    EXPEDITION_UPGRADE_PERK_ORDER,
    EXPEDITION_UPGRADE_PERKS,
)
from econ.data.items import ITEMS, RARITIES
from econ.data.materials import (
    MATERIAL_GROUPS,
    MATERIAL_SUPPLY_BUNDLE,
    MATERIAL_SUPPLY_MARKUP,
    MATERIAL_SUPPLY_MAX_RARITY_ORDER,
    random_universal_material,
)
from econ.data.town_buildings import (
    MAX_BUILDING_TIER,
    TOWN_BUILDINGS,
    building_tier_price,
    production_output_material,
    town_hall_material,
)
from econ.data.town_workers import MAX_WORKER_TIER, TOWN_WORKERS, worker_tier_price
from ui.panels import (
    AMT_W,
    NAME_W,
    QTY_W,
    WEALTH_W,
    Palette,
    Panel,
    RoundPanel,
    chip,
    simple_panel,
)

EFFECT_LABELS = {
    "gold": "gold", "xp": "XP", "cooldown": "cooldown",
    "crit": "crit chance", "luck": "bonus-find chance", "defense": "crime defense",
}
# Above this gold total, the "Auto Buy Materials" button (buildings/
# workers) makes you confirm before it spends -- a small top-up is a
# one-click convenience, a five-figure one deserves a second look.
AUTO_BUY_CONFIRM_THRESHOLD = 10_000
GATHER_CHOICES = [
    app_commands.Choice(name=f"{info['emoji']} {info['name']}", value=key)
    for key, info in TOWN_BUILDINGS.items() if info["kind"] == "production"
]


def resolve_building(query: str, *, production_only: bool = False) -> str | None:
    """Fuzzy-match a building (any of the 16, or just the 8 production
    ones) by key or display name, same idea as cogs/market.py's
    resolve_item. Shared with cogs/info.py's `.info`."""
    q = query.strip().lower().replace(" ", "_").replace("'", "")
    for key, info in TOWN_BUILDINGS.items():
        if production_only and info["kind"] != "production":
            continue
        if key == q or info["name"].lower().replace(" ", "_").replace("'", "") == q:
            return key
    return None


def _resolve_production_building(query: str) -> str | None:
    return resolve_building(query, production_only=True)


def resolve_worker(query: str) -> str | None:
    """Fuzzy-match any of the 20 workers by key or display name.
    Shared with cogs/info.py's `.info`."""
    q = query.strip().lower().replace(" ", "_").replace("'", "")
    for key, info in TOWN_WORKERS.items():
        if key == q or info["name"].lower().replace(" ", "_").replace("'", "") == q:
            return key
    return None


FIRE_CHOICES = [
    app_commands.Choice(name=f"{info['emoji']} {info['name']}", value=key)
    for key, info in TOWN_WORKERS.items()
]


class GatherSession:
    """'Read the Seam': three consecutive materials from a production
    building's own rarity-ordered group (materials.py's MATERIAL_GROUPS
    is already common->legendary in order) are shown in sequence; tap
    whichever candidate continues that sequence among decoys drawn
    from the same group. One wrong tap or a blown timer ends the run
    right there, same as every other minigame in the game."""

    def __init__(
        self, db, gid: int, uid: int, building_key: str, building_tier: int,
        total_level: int, difficulty: str, *, dry_run: bool = False,
        buffs: dict | None = None,
    ):
        self.db = db
        self.gid = gid
        self.uid = uid
        self.building_key = building_key
        self.building_tier = building_tier
        self.total_level = total_level
        self.dry_run = dry_run
        self.buffs = buffs or {}
        self.difficulty = difficulty
        self.tier = formulas.DIFFICULTIES[difficulty]
        self.length = formulas.difficulty_length(
            formulas.GATHER_MIN_ROUNDS, formulas.GATHER_MAX_ROUNDS, difficulty
        )
        self.group = MATERIAL_GROUPS[TOWN_BUILDINGS[building_key]["material_group"]]
        self.correct = 0
        self.done = False
        self.current_panel: RoundPanel | None = None
        self.shown: list[str] = []
        self.target: str | None = None
        self.choices: list[str] = []
        self._roll_round()

    def _footer_text(self, text: str) -> str:
        return f"🧪 TEST MODE · {text}" if self.dry_run else text

    def _roll_round(self) -> None:
        n = len(self.group)
        start = random.randrange(n)
        self.shown = [self.group[(start + i) % n] for i in range(3)]
        self.target = self.group[(start + 3) % n]
        decoy_n = min(formulas.GATHER_DECOYS + self.tier["bonus"], n - 4)
        pool = [m for m in self.group if m not in self.shown and m != self.target]
        self.choices = random.sample(pool, min(decoy_n, len(pool))) + [self.target]
        random.shuffle(self.choices)

    def round_panel(self) -> Panel:
        info = TOWN_BUILDINGS[self.building_key]
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        timeout = max(1.0, formulas.GATHER_ROUND_TIMEOUT * self.tier["timeout_mult"])
        panel = RoundPanel(self, accent=Palette.GOLD, author_id=self.uid, timeout=timeout)
        panel.header(f"{info['emoji']} Read the Seam · {info['name']}")
        seam = " → ".join(ITEMS[m]["emoji"] for m in self.shown)
        panel.text(f"The seam runs {seam} → **?**\nWhat comes next?")
        panel.text(f"`{dots}` ({self.correct}/{self.length})")
        buttons = []
        for key in self.choices:
            btn = ui.Button(
                label=ITEMS[key]["name"][:20], emoji=ITEMS[key]["emoji"],
                style=discord.ButtonStyle.secondary,
            )
            btn.callback = self._make_handler(key)
            buttons.append(btn)
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

    async def on_round_timeout(self, message: discord.Message) -> None:
        if self.done:
            return
        self.done = True
        panel = await self._finish(outcome="fail")
        try:
            await message.edit(view=panel)
        except discord.HTTPException:
            pass

    async def _finish(self, outcome: str) -> Panel:
        info = TOWN_BUILDINGS[self.building_key]
        material = production_output_material(self.building_key, self.building_tier)
        qty = formulas.gather_reward(
            self.building_tier, self.total_level, self.correct, self.length, self.difficulty,
        )
        bonus_material = None
        if (
            outcome == "success" and self.building_tier < MAX_BUILDING_TIER
            and formulas.roll_gather_bridge()
        ):
            bonus_material = production_output_material(self.building_key, self.building_tier + 1)

        if not self.dry_run:
            if qty:
                await self.db.add_item(self.gid, self.uid, material, qty)
            if bonus_material:
                await self.db.add_item(self.gid, self.uid, bonus_material, 1)

        title = f"{info['emoji']} Read the Seam · {info['name']}"
        if outcome == "success":
            panel = Panel(accent=Palette.PURPLE, timeout=None)
            panel.header(f"{title} · Flawless!")
            panel.text("*You trace the seam true, tap by tap, straight to its rich heart.*")
        else:
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header(f"{title} · The Seam Splits")
            panel.text("*You misjudge the vein, and the seam splits away before you finish tracing it.*")

        lines = []
        if qty:
            lines.append(f"{ITEMS[material]['emoji']} {chip((ITEMS[material]['name'], NAME_W), (f'+{qty}', -QTY_W))}")
        else:
            lines.append("Nothing to show for it this time.")
        if bonus_material:
            bonus_info = ITEMS[bonus_material]
            lines.append(f"✨ A rare find: **1x {bonus_info['emoji']} {bonus_info['name']}**!")
        panel.text("\n".join(lines))
        panel.footer(self._footer_text(
            f"{self.tier['emoji']} {self.tier['label']} · {self.correct}/{self.length} rounds cleared"
        ))
        return panel


class PatrolSession:
    """'Round Up': a lineup of townsfolk hides several intruders at
    once (not one named target); tap out every intruder before the
    timer runs out without arresting anyone innocent. A multi-target
    selection task, not a reskin of the single-target identify-among-
    decoys mechanic every other minigame in the game already uses. One
    wrong tap (a false arrest) or a blown timer ends the patrol right
    there."""

    INNOCENT_EMOJI = ("🧑", "👩", "👨", "🧔", "👴", "👵")
    INTRUDER_EMOJI = "🥷"

    def __init__(
        self, db, gid: int, uid: int, watchtower_tier: int, guard_captain_tier: int,
        difficulty: str, *, dry_run: bool = False, buffs: dict | None = None,
    ):
        self.db = db
        self.gid = gid
        self.uid = uid
        self.watchtower_tier = watchtower_tier
        self.guard_captain_tier = guard_captain_tier
        self.dry_run = dry_run
        self.buffs = buffs or {}
        self.difficulty = difficulty
        self.tier = formulas.DIFFICULTIES[difficulty]
        self.length = formulas.difficulty_length(
            formulas.PATROL_MIN_ROUNDS, formulas.PATROL_MAX_ROUNDS, difficulty
        )
        self.correct = 0  # lineups fully cleared
        self.done = False
        self.current_panel: RoundPanel | None = None
        self.lineup: list[bool] = []
        self.slot_emoji: list[str] = []
        self.caught: set[int] = set()
        self.round_deadline: float = 0.0
        self._roll_round()

    def _footer_text(self, text: str) -> str:
        return f"🧪 TEST MODE · {text}" if self.dry_run else text

    def _roll_round(self) -> None:
        size = formulas.PATROL_LINEUP_SIZE[self.difficulty]
        n_intruders = formulas.PATROL_INTRUDER_COUNT[self.difficulty]
        intruder_positions = set(random.sample(range(size), n_intruders))
        self.lineup = [i in intruder_positions for i in range(size)]
        self.slot_emoji = [
            self.INTRUDER_EMOJI if is_intr else random.choice(self.INNOCENT_EMOJI)
            for is_intr in self.lineup
        ]
        self.caught = set()
        timeout = max(1.0, formulas.PATROL_ROUND_TIMEOUT * self.tier["timeout_mult"])
        self.round_deadline = time.time() + timeout

    def _remaining_intruders(self) -> int:
        return sum(1 for i, is_intr in enumerate(self.lineup) if is_intr and i not in self.caught)

    def round_panel(self) -> Panel:
        dots = "🟢" * self.correct + "⚪" * (self.length - self.correct)
        remaining = max(1.0, self.round_deadline - time.time())
        panel = RoundPanel(self, accent=Palette.IRON, author_id=self.uid, timeout=remaining)
        panel.header("🗼 Round Up")
        panel.text(
            f"Catch every intruder hiding in the crowd -- **{self._remaining_intruders()}** left. "
            "Arrest an innocent and the patrol's over."
        )
        panel.text(f"`{dots}` ({self.correct}/{self.length})")
        buttons = []
        for i, emoji in enumerate(self.slot_emoji):
            if i in self.caught:
                btn = ui.Button(emoji="✅", style=discord.ButtonStyle.success, disabled=True)
            else:
                btn = ui.Button(emoji=emoji, style=discord.ButtonStyle.secondary)
                btn.callback = self._make_handler(i)
            buttons.append(btn)
        for i in range(0, len(buttons), 5):
            panel.buttons(*buttons[i : i + 5])
        deadline = int(self.round_deadline)
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
        if not self.lineup[index]:
            self.done = True
            panel = await self._finish(outcome="fail")
            await interaction.response.edit_message(view=panel)
            return
        self.caught.add(index)
        if self._remaining_intruders() > 0:
            next_panel = self.round_panel()
            next_panel.message = interaction.message
            await interaction.response.edit_message(view=next_panel)
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

    async def on_round_timeout(self, message: discord.Message) -> None:
        if self.done:
            return
        self.done = True
        panel = await self._finish(outcome="fail")
        try:
            await message.edit(view=panel)
        except discord.HTTPException:
            pass

    async def _finish(self, outcome: str) -> Panel:
        gold = formulas.patrol_reward(
            self.watchtower_tier, self.guard_captain_tier, self.correct, self.length, self.difficulty,
        )
        if gold:
            gold = round(apply_gold_buff(gold, self.buffs))
        if not self.dry_run and gold:
            await self.db.add_gold(self.gid, self.uid, gold)

        if outcome == "success":
            panel = Panel(accent=Palette.PURPLE, timeout=None)
            panel.header("🗼 Round Up · Flawless!")
            panel.text("*Every last intruder is in irons before the gate even shuts.*")
        else:
            panel = Panel(accent=Palette.RED, timeout=None)
            panel.header("🗼 Round Up · The Patrol Ends")
            panel.text("*A face slips past you in the crowd, and the patrol falls apart.*")

        if gold:
            panel.text(f"💰 {chip(('Confiscated', NAME_W), (f'{gold:,}', -AMT_W))} 🪙")
        else:
            panel.text("💰 No gold this time.")
        panel.footer(self._footer_text(
            f"{self.tier['emoji']} {self.tier['label']} · {self.correct}/{self.length} rounds cleared"
        ))
        return panel


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


def _material_rarity_order(key: str) -> int:
    return list(RARITIES.keys()).index(ITEMS[key]["rarity"])


async def _auto_buy_plan(
    db, gid: int, uid: int, materials: dict[str, int],
) -> tuple[dict[str, int], int] | None:
    """(missing_qty, gold_cost) to top up every shortfall in `materials`
    via Builder's Supply, at the same per-unit price `.supply` charges
    (see MATERIAL_SUPPLY_MARKUP). None if ANY shortfall material is
    rarer than .supply stocks (see MATERIAL_SUPPLY_MAX_RARITY_ORDER) --
    in that case there's nothing an auto-buy button could safely cover,
    so the caller should hide it rather than offer a partial top-up.
    An empty `missing` dict (nothing short) is a valid, non-None result."""
    missing: dict[str, int] = {}
    total_cost = 0
    for mat, qty in materials.items():
        owned = await db.get_item_qty(gid, uid, mat)
        shortfall = qty - owned
        if shortfall <= 0:
            continue
        if _material_rarity_order(mat) > MATERIAL_SUPPLY_MAX_RARITY_ORDER:
            return None
        missing[mat] = shortfall
        total_cost += round(ITEMS[mat]["value"] * MATERIAL_SUPPLY_MARKUP * shortfall)
    return missing, total_cost


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

    @commands.hybrid_command(name="townhall", description="Found your town (150k gold), or upgrade Town Hall")
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

        population = town["population"]

        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"🏰 {_town_name(display_name)}")
        panel.text(
            f"Town Hall **Level {level}**/{formulas.TOWN_HALL_MAX_LEVEL} · "
            f"🏗️ {len(building_tiers)}/{len(TOWN_BUILDINGS)} buildings · "
            f"👷 {len(worker_tiers)}/{len(TOWN_WORKERS)} workers hired\n"
            f"🧑‍🤝‍🧑 Population **{population:,}**"
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

        hint = await self._next_upgrade_hint(gid, uid, level, building_tiers, worker_tiers)
        if hint:
            panel.divider()
            panel.subheader("🎯 Next Move")
            panel.text(hint)

        panel.footer("`.buildings` to build/upgrade · `.workers` to hire · `.supply` for materials")
        if total_pending > 0:
            collect_btn = ui.Button(label="Collect All", emoji="📦", style=discord.ButtonStyle.success)
            collect_btn.callback = self._on_collect_button
            panel.buttons(collect_btn)
        return panel

    async def _next_upgrade_hint(
        self, gid: int, uid: int, level: int, building_tiers: dict[str, int], worker_tiers: dict[str, int],
    ) -> str | None:
        """Cheapest next upgrade across Town Hall/buildings/workers, by
        gold cost alone -- a quick "what should I do next" nudge, not a
        full ledger of every option (see `.buildings`/`.workers` for that)."""
        candidates: list[tuple[int, str, str]] = []

        if level < formulas.TOWN_HALL_MAX_LEVEL:
            gold, _qty = formulas.town_hall_upgrade_cost(level + 1)
            candidates.append((gold, f"Town Hall to Level {level + 1}", "🏰"))

        for key, info in TOWN_BUILDINGS.items():
            if level < info["unlock_hall_level"]:
                continue
            tier = building_tiers.get(key, 0)
            if tier >= MAX_BUILDING_TIER:
                continue
            gold, _mats = building_tier_price(key, tier + 1)
            verb = "Build" if tier == 0 else f"Upgrade to Tier {tier + 1}"
            candidates.append((gold, f"{verb} {info['name']}", info["emoji"]))

        lodge_tier = building_tiers.get("workers_lodge", 0)
        if lodge_tier > 0:
            used, capacity = await town_lib.hired_worker_slots_used(self.db, gid, uid)
            for key, info in TOWN_WORKERS.items():
                tier = worker_tiers.get(key, 0)
                if tier >= MAX_WORKER_TIER:
                    continue
                if tier == 0 and used >= capacity:
                    continue  # no free hire slot for a brand new worker
                gold, _mats = worker_tier_price(key, tier + 1)
                verb = "Hire" if tier == 0 else f"Train to Tier {tier + 1}"
                candidates.append((gold, f"{verb} {info['name']}", info["emoji"]))

        if not candidates:
            return None
        gold, label, emoji = min(candidates, key=lambda c: c[0])
        return f"{emoji} Cheapest next step: **{label}** -- {gold:,} gold (+materials)"

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
    # "Read the Seam" -- the active counterpart to .collect's idle
    # trickle. See GatherSession above for the mechanic. Difficulty is
    # gated by the BUILDING's own tier (there's no skill level to gate
    # it by): Medium needs tier 3+, Hard needs it maxed.

    @commands.hybrid_command(
        name="gather",
        description="Read the Seam: an active minigame for materials from a built production building",
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
        buffs = await active_buff_totals(self.db, gid, uid)
        cooldown = apply_cooldown_buff(formulas.GATHER_COOLDOWN, buffs)
        cooldown_key = f"gather_{key}"
        last = await self.db.get_minigame_cooldown(gid, uid, cooldown_key)
        now = time.time()
        if now < last + cooldown:
            await ctx.send(
                view=simple_panel(
                    f"The {info['name']} needs more time before it can be worked again. "
                    f"Ready <t:{int(last + cooldown)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        await self._send_gather_difficulty_picker(ctx, key, tier, dry_run=False)

    @commands.hybrid_command(
        name="gathertest",
        description="[Admin] Try the Read the Seam minigame at any building tier, no cooldown/rewards",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(
        building="Which production building's minigame to test",
        tier="Building tier to simulate (default 1)",
    )
    @app_commands.choices(building=GATHER_CHOICES)
    async def gathertest(
        self, ctx: commands.Context, building: str,
        tier: commands.Range[int, 1, MAX_BUILDING_TIER] = 1,
    ):
        key = _resolve_production_building(building)
        if key is None:
            await ctx.send(
                view=simple_panel(f"No such production building: **{building}**.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        await self._send_gather_difficulty_picker(ctx, key, tier, dry_run=True)

    async def _send_gather_difficulty_picker(
        self, ctx: commands.Context, building_key: str, building_tier: int, *, dry_run: bool,
    ) -> None:
        """Easy is always open (once built); Medium/Hard unlock at
        GATHER_TIER_UNLOCK's thresholds in the BUILDING's own tier.
        Picking a tier starts the attempt (and, for a real run, burns
        the cooldown)."""
        info = TOWN_BUILDINGS[building_key]
        panel = Panel(accent=Palette.GOLD, author_id=ctx.author.id, timeout=60)
        panel.header(f"{info['emoji']} Read the Seam · {info['name']}")
        panel.text(
            "*Pick your difficulty. The seam shows three linked materials -- tap "
            "whichever continues the pattern before time runs out. One wrong tap "
            "or a blown timer ends the run.*"
        )
        lines, buttons = [], []
        for key in formulas.DIFFICULTY_ORDER:
            tier_cfg = formulas.DIFFICULTIES[key]
            length = formulas.difficulty_length(
                formulas.GATHER_MIN_ROUNDS, formulas.GATHER_MAX_ROUNDS, key
            )
            need = formulas.GATHER_TIER_UNLOCK[key]
            unlocked = dry_run or building_tier >= need
            mult = f"×{tier_cfg['reward_mult']:.2f}"
            if unlocked:
                lines.append(
                    f"{tier_cfg['emoji']} {chip((tier_cfg['label'], NAME_W), (mult, -AMT_W))} "
                    f"· {length} rounds"
                )
            else:
                lines.append(
                    f"🔒 {chip((tier_cfg['label'], NAME_W), (mult, -AMT_W))} "
                    f"· needs Tier {need} (you're {building_tier})"
                )
            btn = ui.Button(
                label=tier_cfg["label"], emoji=tier_cfg["emoji"],
                style=discord.ButtonStyle.secondary, disabled=not unlocked,
            )
            if unlocked:
                btn.callback = self._make_gather_start_handler(building_key, key, building_tier, dry_run)
            buttons.append(btn)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._on_generic_cancel
        buttons.append(cancel_btn)
        panel.text("\n".join(lines))
        panel.buttons(*buttons)
        panel.message = await ctx.send(view=panel)

    def _make_gather_start_handler(
        self, building_key: str, difficulty: str, building_tier: int, dry_run: bool,
    ):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            buffs: dict = {}
            if not dry_run:
                buffs = await active_buff_totals(self.db, gid, uid)
                cooldown = apply_cooldown_buff(formulas.GATHER_COOLDOWN, buffs)
                cooldown_key = f"gather_{building_key}"
                last = await self.db.get_minigame_cooldown(gid, uid, cooldown_key)
                now = time.time()
                if now < last + cooldown:
                    await interaction.response.edit_message(
                        view=simple_panel(
                            f"Too late, the window's closed. Ready <t:{int(last + cooldown)}:R>.",
                            accent=Palette.RED,
                        )
                    )
                    return
                # Cooldown burns the moment the attempt starts, win or
                # lose, so walking away mid-attempt can't reroll a bad run.
                await self.db.set_minigame_cooldown(gid, uid, cooldown_key, now)
            total_level = await self.db.total_level(gid, uid)
            session = GatherSession(
                self.db, gid, uid, building_key, building_tier, total_level, difficulty,
                dry_run=dry_run, buffs=buffs,
            )
            panel = session.round_panel()
            panel.message = interaction.message
            await interaction.response.edit_message(view=panel)
        return handler

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

    async def _build_building_upgrade_panel(self, gid: int, uid: int, key: str) -> Panel:
        """Confirm panel for building `key`'s next tier -- shared by the
        `.buildings` select and the auto-buy flow's "back"/refresh steps,
        so both always show the same live gold/material picture."""
        town = await self.db.get_town(gid, uid)
        tier = await self.db.get_building_tier(gid, uid, key)
        info = TOWN_BUILDINGS[key]
        if tier <= 0 and town["hall_level"] < info["unlock_hall_level"]:
            return simple_panel(
                f"**{info['name']}** needs Town Hall level {info['unlock_hall_level']}.",
                accent=Palette.RED,
            )
        if tier >= MAX_BUILDING_TIER:
            return simple_panel(f"**{info['name']}** is already fully built.", accent=Palette.RED)
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
        confirm_btn.callback = self._make_building_confirm_handler(key, next_tier)
        buttons = [confirm_btn]
        plan = await _auto_buy_plan(self.db, gid, uid, materials)
        if plan is not None and plan[0]:
            _missing, cost = plan
            auto_buy_btn = ui.Button(
                label=f"Auto Buy Materials ({cost:,}g)", emoji="🧱", style=discord.ButtonStyle.secondary,
            )
            auto_buy_btn.callback = self._make_auto_buy_handler("building", key)
            buttons.append(auto_buy_btn)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._on_generic_cancel
        buttons.append(cancel_btn)
        panel.buttons(*buttons)
        return panel

    async def _on_building_select(self, interaction: discord.Interaction) -> None:
        key = interaction.data["values"][0]
        panel = await self._build_building_upgrade_panel(interaction.guild_id, interaction.user.id, key)
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
            more_btn = ui.Button(label="Back to Buildings", emoji="🏗️", style=discord.ButtonStyle.secondary)
            more_btn.callback = self._on_back_to_buildings
            panel.buttons(more_btn)
            await interaction.response.edit_message(view=panel)
        return handler

    async def _on_back_to_buildings(self, interaction: discord.Interaction) -> None:
        panel = await self._build_buildings_panel(
            interaction.guild_id, interaction.user.id, interaction.user.display_name
        )
        panel.message = interaction.message
        await interaction.response.edit_message(view=panel)

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

    async def _build_worker_upgrade_panel(self, gid: int, uid: int, key: str) -> Panel:
        """Confirm panel for worker `key`'s next tier -- shared by the
        `.workers` select and the auto-buy flow's "back"/refresh steps."""
        info = TOWN_WORKERS[key]
        tier = await self.db.get_worker_tier(gid, uid, key)
        used, capacity = await town_lib.hired_worker_slots_used(self.db, gid, uid)
        if tier <= 0 and used >= capacity:
            return simple_panel("No free hire slots. Upgrade your Workers' Lodge first.", accent=Palette.RED)
        if tier >= MAX_WORKER_TIER:
            return simple_panel(f"**{info['name']}** is already fully trained.", accent=Palette.RED)
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
        confirm_btn.callback = self._make_worker_confirm_handler(key, next_tier)
        buttons = [confirm_btn]
        plan = await _auto_buy_plan(self.db, gid, uid, materials)
        if plan is not None and plan[0]:
            _missing, cost = plan
            auto_buy_btn = ui.Button(
                label=f"Auto Buy Materials ({cost:,}g)", emoji="🧱", style=discord.ButtonStyle.secondary,
            )
            auto_buy_btn.callback = self._make_auto_buy_handler("worker", key)
            buttons.append(auto_buy_btn)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._on_generic_cancel
        buttons.append(cancel_btn)
        panel.buttons(*buttons)
        return panel

    async def _on_worker_select(self, interaction: discord.Interaction) -> None:
        key = interaction.data["values"][0]
        panel = await self._build_worker_upgrade_panel(interaction.guild_id, interaction.user.id, key)
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
            more_btn = ui.Button(label="Back to Workers", emoji="👷", style=discord.ButtonStyle.secondary)
            more_btn.callback = self._on_back_to_workers
            panel.buttons(more_btn)
            await interaction.response.edit_message(view=panel)
        return handler

    async def _on_back_to_workers(self, interaction: discord.Interaction) -> None:
        panel = await self._build_workers_panel(
            interaction.guild_id, interaction.user.id, interaction.user.display_name
        )
        if not isinstance(panel, Panel):
            panel = simple_panel("Build a Workers' Lodge first (see `.buildings`).", accent=Palette.RED)
        panel.message = interaction.message
        await interaction.response.edit_message(view=panel)

    # ── "Auto Buy Materials": one click to top up a shortfall from ───────
    # Builder's Supply, offered on the buildings/workers confirm panels
    # ONLY when every short material is something .supply actually sells
    # (see _auto_buy_plan) -- a rare+ shortfall means no button at all,
    # rather than a button that can't fully solve the shortfall. Above
    # AUTO_BUY_CONFIRM_THRESHOLD gold it asks for a second confirm first.

    async def _rebuild_upgrade_panel(self, gid: int, uid: int, kind: str, key: str) -> Panel:
        if kind == "building":
            return await self._build_building_upgrade_panel(gid, uid, key)
        return await self._build_worker_upgrade_panel(gid, uid, key)

    async def _current_upgrade_materials(
        self, gid: int, uid: int, kind: str, key: str,
    ) -> dict[str, int] | None:
        """This kind/key's next-tier material requirement, or None if
        it's maxed/locked out from under the auto-buy button."""
        if kind == "building":
            tier = await self.db.get_building_tier(gid, uid, key)
            if tier >= MAX_BUILDING_TIER:
                return None
            _gold, materials = building_tier_price(key, tier + 1)
            return materials
        tier = await self.db.get_worker_tier(gid, uid, key)
        if tier >= MAX_WORKER_TIER:
            return None
        _gold, materials = worker_tier_price(key, tier + 1)
        return materials

    def _make_auto_buy_handler(self, kind: str, key: str):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            materials = await self._current_upgrade_materials(gid, uid, kind, key)
            plan = await _auto_buy_plan(self.db, gid, uid, materials) if materials is not None else None
            if plan is None or not plan[0]:
                panel = await self._rebuild_upgrade_panel(gid, uid, kind, key)
                await interaction.response.edit_message(view=panel)
                return
            missing, cost = plan
            if cost > AUTO_BUY_CONFIRM_THRESHOLD:
                panel = self._build_auto_buy_confirm_panel(uid, kind, key, missing, cost)
                await interaction.response.edit_message(view=panel)
                return
            await self._execute_auto_buy(interaction, kind, key, missing, cost)
        return handler

    def _build_auto_buy_confirm_panel(
        self, uid: int, kind: str, key: str, missing: dict[str, int], cost: int,
    ) -> Panel:
        panel = Panel(accent=Palette.IRON, author_id=uid, timeout=60)
        panel.header("🧱 Auto Buy Materials?")
        lines = [f"{ITEMS[m]['emoji']} {ITEMS[m]['name']} x{q:,}" for m, q in missing.items()]
        panel.text(
            "\n".join(lines) + f"\n\nTotal: **{formulas.fmt_gold(cost)}** from Builder's Supply"
        )
        confirm_btn = ui.Button(label="Buy It All", emoji="🧱", style=discord.ButtonStyle.success)
        confirm_btn.callback = self._make_auto_buy_confirm_handler(kind, key)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._make_auto_buy_cancel_handler(kind, key)
        panel.buttons(confirm_btn, cancel_btn)
        return panel

    def _make_auto_buy_confirm_handler(self, kind: str, key: str):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            materials = await self._current_upgrade_materials(gid, uid, kind, key)
            plan = await _auto_buy_plan(self.db, gid, uid, materials) if materials is not None else None
            if plan is None or not plan[0]:
                panel = await self._rebuild_upgrade_panel(gid, uid, kind, key)
                await interaction.response.edit_message(view=panel)
                return
            missing, cost = plan
            await self._execute_auto_buy(interaction, kind, key, missing, cost)
        return handler

    def _make_auto_buy_cancel_handler(self, kind: str, key: str):
        async def handler(interaction: discord.Interaction) -> None:
            panel = await self._rebuild_upgrade_panel(interaction.guild_id, interaction.user.id, kind, key)
            await interaction.response.edit_message(view=panel)
        return handler

    async def _execute_auto_buy(
        self, interaction: discord.Interaction, kind: str, key: str, missing: dict[str, int], cost: int,
    ) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if not await self.db.spend_gold(gid, uid, cost):
            await interaction.response.edit_message(
                view=simple_panel(f"That would cost {cost:,} gold.", accent=Palette.RED)
            )
            return
        for mat, qty in missing.items():
            await self.db.add_item(gid, uid, mat, qty)
        panel = await self._rebuild_upgrade_panel(gid, uid, kind, key)
        await interaction.response.edit_message(view=panel)

    # ══════════════════════════════ .fire ════════════════════════════════
    # The other half of .workers: dismiss a hired worker back to
    # unhired (tier 0), freeing their Lodge slot for someone else. No
    # refund of the gold/materials already spent training them -- same
    # "sunk cost, no take-backs" rule as every other upgrade in the game.

    @commands.hybrid_command(name="fire", description="Dismiss a hired worker, freeing their hire slot (no refund)")
    @commands.guild_only()
    @app_commands.describe(worker="Which hired worker to dismiss")
    @app_commands.choices(worker=FIRE_CHOICES)
    async def fire(self, ctx: commands.Context, *, worker: str):
        gid, uid = ctx.guild.id, ctx.author.id
        key = resolve_worker(worker)
        if key is None:
            await ctx.send(
                view=simple_panel(f"No such worker: **{worker}**.", accent=Palette.RED), ephemeral=True,
            )
            return
        info = TOWN_WORKERS[key]
        tier = await self.db.get_worker_tier(gid, uid, key)
        if tier <= 0:
            await ctx.send(
                view=simple_panel(f"You haven't hired a **{info['name']}**.", accent=Palette.RED),
                ephemeral=True,
            )
            return

        panel = Panel(accent=Palette.RED, author_id=uid, timeout=60)
        panel.header(f"🔥 Fire {info['name']}?")
        panel.text(
            f"Currently **Tier {tier}**. Firing resets them to unhired -- no refund of "
            "what you spent hiring or training them, but the slot opens up and you "
            "can hire (and re-train from tier 1) someone new."
        )
        confirm_btn = ui.Button(label="Fire", emoji="🔥", style=discord.ButtonStyle.danger)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        confirm_btn.callback = self._make_fire_confirm_handler(key)
        cancel_btn.callback = self._on_generic_cancel
        panel.buttons(confirm_btn, cancel_btn)
        panel.message = await ctx.send(view=panel)

    def _make_fire_confirm_handler(self, key: str):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            tier = await self.db.get_worker_tier(gid, uid, key)
            info = TOWN_WORKERS[key]
            if tier <= 0:
                await interaction.response.edit_message(
                    view=simple_panel(f"**{info['name']}** is already unhired.", accent=Palette.RED)
                )
                return
            await self.db.set_worker_tier(gid, uid, key, 0)
            panel = Panel(accent=Palette.GOLD, timeout=None)
            panel.header(f"🔥 {info['name']} Dismissed")
            panel.text("Their hire slot is free again. `.workers` to hire someone new.")
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

        # Rare+ items simply aren't listed here at all -- a dead row
        # that can't be bought is just clutter, not information; the
        # footer below already says where to actually get them.
        lines = []
        select = ui.Select(placeholder="🧱 Buy a bundle…")
        for key in item_keys:
            if self._rarity_order(key) > MATERIAL_SUPPLY_MAX_RARITY_ORDER:
                continue
            info = ITEMS[key]
            owned = await self.db.get_item_qty(gid, uid, key)
            price = round(info["value"] * MATERIAL_SUPPLY_MARKUP * MATERIAL_SUPPLY_BUNDLE)
            lines.append(
                f"{info['emoji']} {chip((info['name'], NAME_W), (f'x{owned}', QTY_W), (f'{price:,}', -AMT_W))} 🪙"
            )
            select.add_option(
                label=f"{info['name']} x{MATERIAL_SUPPLY_BUNDLE} · {price:,}g"[:100],
                value=key,
                emoji=info["emoji"],
            )
        panel.text("\n".join(lines) if lines else "*Nothing common/uncommon left in this group.*")
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

        select.callback = self._make_supply_buy_handler(category_key)
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

    def _make_supply_buy_handler(self, category_key: str):
        async def handler(interaction: discord.Interaction) -> None:
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
            more_btn = ui.Button(label="Buy More", emoji="🧱", style=discord.ButtonStyle.secondary)
            more_btn.callback = self._make_supply_return_handler(category_key)
            panel.buttons(more_btn)
            await interaction.response.edit_message(view=panel)
        return handler

    def _make_supply_return_handler(self, category_key: str):
        async def handler(interaction: discord.Interaction) -> None:
            panel = await self._build_supply_panel(interaction.guild_id, interaction.user.id, category_key)
            panel.message = interaction.message
            await interaction.response.edit_message(view=panel)
        return handler

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
    # "Round Up" -- see PatrolSession above for the mechanic. Difficulty
    # is gated by the Watchtower's own tier, same idea as .gather.

    @commands.hybrid_command(
        name="patrol", description="Round Up: an active minigame to catch intruders (needs a Watchtower)",
    )
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
        buffs = await active_buff_totals(self.db, gid, uid)
        cooldown = apply_cooldown_buff(formulas.PATROL_COOLDOWN, buffs)
        last = await self.db.get_minigame_cooldown(gid, uid, "patrol")
        now = time.time()
        if now < last + cooldown:
            await ctx.send(
                view=simple_panel(f"Still on watch. Ready <t:{int(last + cooldown)}:R>.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        guard_captain_tier = await self.db.get_worker_tier(gid, uid, "guard_captain")
        await self._send_patrol_difficulty_picker(ctx, watchtower_tier, guard_captain_tier, dry_run=False)

    @commands.hybrid_command(
        name="patroltest",
        description="[Admin] Try the Round Up minigame at any Watchtower tier, no cooldown/rewards",
    )
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @app_commands.describe(tier="Watchtower tier to simulate (default 1)")
    async def patroltest(
        self, ctx: commands.Context, tier: commands.Range[int, 1, MAX_BUILDING_TIER] = 1,
    ):
        await self._send_patrol_difficulty_picker(ctx, tier, 0, dry_run=True)

    async def _send_patrol_difficulty_picker(
        self, ctx: commands.Context, watchtower_tier: int, guard_captain_tier: int, *, dry_run: bool,
    ) -> None:
        panel = Panel(accent=Palette.GOLD, author_id=ctx.author.id, timeout=60)
        panel.header("🗼 Round Up")
        panel.text(
            "*Pick your difficulty. A lineup of townsfolk hides several intruders "
            "at once -- tap out every last one before the timer runs out. Arrest "
            "one innocent face and the whole patrol falls apart.*"
        )
        lines, buttons = [], []
        for key in formulas.DIFFICULTY_ORDER:
            tier_cfg = formulas.DIFFICULTIES[key]
            length = formulas.difficulty_length(
                formulas.PATROL_MIN_ROUNDS, formulas.PATROL_MAX_ROUNDS, key
            )
            need = formulas.PATROL_TIER_UNLOCK[key]
            unlocked = dry_run or watchtower_tier >= need
            mult = f"×{tier_cfg['reward_mult']:.2f}"
            size = formulas.PATROL_LINEUP_SIZE[key]
            n_intr = formulas.PATROL_INTRUDER_COUNT[key]
            if unlocked:
                lines.append(
                    f"{tier_cfg['emoji']} {chip((tier_cfg['label'], NAME_W), (mult, -AMT_W))} "
                    f"· {length} lineups · {n_intr}/{size} intruders"
                )
            else:
                lines.append(
                    f"🔒 {chip((tier_cfg['label'], NAME_W), (mult, -AMT_W))} "
                    f"· needs Watchtower Tier {need} (you're {watchtower_tier})"
                )
            btn = ui.Button(
                label=tier_cfg["label"], emoji=tier_cfg["emoji"],
                style=discord.ButtonStyle.secondary, disabled=not unlocked,
            )
            if unlocked:
                btn.callback = self._make_patrol_start_handler(
                    watchtower_tier, guard_captain_tier, key, dry_run
                )
            buttons.append(btn)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._on_generic_cancel
        buttons.append(cancel_btn)
        panel.text("\n".join(lines))
        panel.buttons(*buttons)
        panel.message = await ctx.send(view=panel)

    def _make_patrol_start_handler(
        self, watchtower_tier: int, guard_captain_tier: int, difficulty: str, dry_run: bool,
    ):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            buffs: dict = {}
            if not dry_run:
                buffs = await active_buff_totals(self.db, gid, uid)
                cooldown = apply_cooldown_buff(formulas.PATROL_COOLDOWN, buffs)
                last = await self.db.get_minigame_cooldown(gid, uid, "patrol")
                now = time.time()
                if now < last + cooldown:
                    await interaction.response.edit_message(
                        view=simple_panel(
                            f"Too late, the window's closed. Ready <t:{int(last + cooldown)}:R>.",
                            accent=Palette.RED,
                        )
                    )
                    return
                await self.db.set_minigame_cooldown(gid, uid, "patrol", now)
            session = PatrolSession(
                self.db, gid, uid, watchtower_tier, guard_captain_tier, difficulty,
                dry_run=dry_run, buffs=buffs,
            )
            panel = session.round_panel()
            panel.message = interaction.message
            await interaction.response.edit_message(view=panel)
        return handler

    # ══════════════════════════════ .caravan ════════════════════════════
    # The idle half of "going out" (Scout the Trail is the active half):
    # send one caravan for real hours, come back later to collect. Routes
    # are gated by POPULATION, not hall level/a building tier, since a
    # caravan is about how much town you can spare (see
    # econ/data/caravans.py). Only one can be out at a time.

    @commands.hybrid_command(
        name="caravan", description="Send a trade caravan out, or check on one that's already out",
    )
    @commands.guild_only()
    async def caravan(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        town = await self.db.get_town(gid, uid)
        if town["hall_level"] <= 0:
            await ctx.send(
                view=simple_panel("Found your town with `.townhall` first.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        panel = await self._build_caravan_panel(gid, uid, ctx.author.display_name)
        panel.message = await ctx.send(view=panel)

    async def _build_caravan_panel(self, gid: int, uid: int, display_name: str) -> Panel:
        caravan = await self.db.get_caravan(gid, uid)
        if caravan is not None:
            return self._build_caravan_status_panel(uid, caravan)
        return await self._build_caravan_picker_panel(gid, uid, display_name)

    def _build_caravan_status_panel(self, uid: int, caravan: dict) -> Panel:
        route = CARAVAN_ROUTES[caravan["route"]]
        ready_at = formulas.caravan_ready_at(caravan["departed_at"], route["duration_hours"])
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"{route['emoji']} {route['name']} · Out on the Road")
        if time.time() < ready_at:
            panel.text(f"*{route['flavor']}*\nDue back <t:{int(ready_at)}:R>.")
            panel.footer("Check back with `.caravan` once it's returned.")
            return panel
        panel.text(f"*{route['flavor']}*\nThe caravan just rolled back into town!")
        collect_btn = ui.Button(label="Welcome It Home", emoji="🎉", style=discord.ButtonStyle.success)
        collect_btn.callback = self._on_caravan_collect
        panel.buttons(collect_btn)
        return panel

    async def _build_caravan_picker_panel(self, gid: int, uid: int, display_name: str) -> Panel:
        population = await town_lib.get_population(self.db, gid, uid)
        user = await self.db.get_user(gid, uid)
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=120)
        panel.header(f"🐎 {_town_name(display_name)} · Send a Caravan")
        panel.text(
            f"Population **{population:,}** decides which routes you can spare the hands for. "
            "*Pick a route -- it takes real hours to complete, so check back later with `.caravan`.*"
        )
        lines, buttons = [], []
        for key in CARAVAN_ROUTE_ORDER:
            route = CARAVAN_ROUTES[key]
            unlocked = population >= route["min_population"]
            need = route["min_population"]
            cost = f"{route['send_gold_cost']:,}"
            hours = route["duration_hours"]
            if unlocked:
                lines.append(
                    f"{route['emoji']} {chip((route['name'], NAME_W), (cost, -WEALTH_W))} 🪙 "
                    f"· {hours}h · ~{route['base_gold_reward']:,} gold back"
                )
            else:
                lines.append(f"🔒 {chip((route['name'], NAME_W), (f'needs pop. {need:,}', -13))}")
            btn = ui.Button(
                label=route["name"], emoji=route["emoji"],
                style=discord.ButtonStyle.secondary, disabled=not unlocked,
            )
            if unlocked:
                btn.callback = self._make_caravan_send_handler(key)
            buttons.append(btn)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel_btn.callback = self._on_generic_cancel
        buttons.append(cancel_btn)
        panel.text("\n".join(lines))
        panel.footer(f"Your purse: {user['gold']:,} gold")
        panel.buttons(*buttons)
        return panel

    def _make_caravan_send_handler(self, route_key: str):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            route = CARAVAN_ROUTES[route_key]
            population = await town_lib.get_population(self.db, gid, uid)
            if population < route["min_population"]:
                await interaction.response.edit_message(
                    view=simple_panel(
                        f"Your town's population dipped below what **{route['name']}** needs.",
                        accent=Palette.RED,
                    )
                )
                return
            if not await self.db.spend_gold(gid, uid, route["send_gold_cost"]):
                await interaction.response.edit_message(
                    view=simple_panel(
                        f"Sending the **{route['name']}** costs {route['send_gold_cost']:,} gold.",
                        accent=Palette.RED,
                    )
                )
                return
            started = await self.db.start_caravan(gid, uid, route_key, time.time())
            if not started:
                await self.db.add_gold(gid, uid, route["send_gold_cost"])
                await interaction.response.edit_message(
                    view=simple_panel("A caravan is already out.", accent=Palette.RED)
                )
                return
            panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
            panel.header(f"{route['emoji']} {route['name']} Departs")
            ready_at = formulas.caravan_ready_at(time.time(), route["duration_hours"])
            panel.text(f"*{route['flavor']}*\nDue back <t:{int(ready_at)}:R>.")
            panel.footer("Check back with `.caravan` once it's returned.")
            await interaction.response.edit_message(view=panel)
        return handler

    async def _on_caravan_collect(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        caravan = await self.db.get_caravan(gid, uid)
        if caravan is None:
            await interaction.response.edit_message(
                view=simple_panel("No caravan to collect.", accent=Palette.RED)
            )
            return
        route = CARAVAN_ROUTES[caravan["route"]]
        ready_at = formulas.caravan_ready_at(caravan["departed_at"], route["duration_hours"])
        if time.time() < ready_at:
            await interaction.response.edit_message(
                view=simple_panel(f"Not back yet. Ready <t:{int(ready_at)}:R>.", accent=Palette.RED)
            )
            return
        town_totals = await town_lib.town_bonus_totals(self.db, gid, uid)
        defense_bonus = town_totals.get("defense", 0.0)
        label, gold_mult, material_mult = formulas.roll_caravan_outcome(defense_bonus)
        gold = formulas.caravan_gold_reward(route["base_gold_reward"], gold_mult)
        qty = formulas.caravan_material_qty(material_mult)
        material = random_universal_material(route["reward_rarity"])
        await self.db.add_gold(gid, uid, gold)
        if qty > 0:
            await self.db.add_item(gid, uid, material, qty)
        await self.db.clear_caravan(gid, uid)

        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"{route['emoji']} {label}!")
        mat_info = ITEMS[material]
        lines = [f"*{route['flavor']}*", f"+{formulas.fmt_gold(gold)}"]
        if qty > 0:
            lines.append(f"+{qty}x {mat_info['emoji']} {mat_info['name']}")
        panel.text("\n".join(lines))
        again_btn = ui.Button(label="Send Another", emoji="🐎", style=discord.ButtonStyle.primary)
        again_btn.callback = self._on_caravan_send_again
        panel.buttons(again_btn)
        await interaction.response.edit_message(view=panel)

    async def _on_caravan_send_again(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        panel = await self._build_caravan_picker_panel(gid, uid, interaction.user.display_name)
        await interaction.response.edit_message(view=panel)

    # ══════════════════════════════ .expedition ═════════════════════════
    # The only way to earn Population. Similar to .venture (pick one of
    # a few risk tiers, each a genuine success/loss gamble) but paced
    # over real time instead of resolved in one shot: 5 legs, one choice
    # every 15 minutes, so a full trip takes real, deliberate check-ins.

    @commands.hybrid_command(
        name="expedition", description="Send settlers out to grow your town's Population (needs a town)",
    )
    @commands.guild_only()
    async def expedition(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        town = await self.db.get_town(gid, uid)
        if town["hall_level"] <= 0:
            await ctx.send(
                view=simple_panel("Found your town with `.townhall` first.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        panel = await self._build_expedition_panel(gid, uid, ctx.author.display_name)
        panel.message = await ctx.send(view=panel)

    async def _build_expedition_panel(self, gid: int, uid: int, display_name: str) -> Panel:
        town = await self.db.get_town(gid, uid)
        perks = formulas.expedition_upgrade_perks(town["expedition_upgrades"])
        expedition = await self.db.get_expedition(gid, uid)
        if expedition is None:
            return await self._build_expedition_start_panel(gid, uid, display_name, perks)
        now = time.time()
        cooldown = formulas.expedition_cooldown(perks)
        legs = formulas.expedition_legs(perks)
        ready_at = expedition["last_choice_at"] + cooldown
        if now < ready_at:
            panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
            panel.header(f"🧭 {_town_name(display_name)} · Expedition Under Way")
            panel.text(
                f"Leg **{expedition['legs_done']}/{legs}** done, "
                f"**+{expedition['population_gained']:,}** Population so far this trip.\n"
                f"Next decision ready <t:{int(ready_at)}:R>."
            )
            return panel
        return await self._build_expedition_choice_panel(gid, uid, expedition, perks)

    async def _build_expedition_start_panel(
        self, gid: int, uid: int, display_name: str, perks: list[str],
    ) -> Panel:
        user = await self.db.get_user(gid, uid)
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=60)
        panel.header(f"🧭 {_town_name(display_name)} · Send Settlers Out?")
        cooldown_min = formulas.expedition_cooldown(perks) // 60
        legs = formulas.expedition_legs(perks)
        panel.text(
            f"**{formulas.fmt_gold(formulas.EXPEDITION_START_COST)}** funds an expedition of "
            f"**{legs}** legs -- one decision every **{cooldown_min} minutes**, "
            "real time. This is the only way to grow your town's **Population**, which feeds a "
            "real gold bonus.\n\n"
            f"Your purse: {user['gold']:,} gold"
        )
        confirm_btn = ui.Button(label="Send Them Out", emoji="🧭", style=discord.ButtonStyle.success)
        confirm_btn.callback = self._on_expedition_start_confirm
        buttons = [confirm_btn]
        if len(perks) < formulas.EXPEDITION_UPGRADE_MAX_LEVEL:
            upgrade_btn = ui.Button(
                label=f"Upgrade ({len(perks)}/{formulas.EXPEDITION_UPGRADE_MAX_LEVEL})",
                emoji="📈", style=discord.ButtonStyle.primary,
            )
            upgrade_btn.callback = self._on_expedition_upgrade_open
            buttons.append(upgrade_btn)
        cancel_btn = ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._on_generic_cancel
        buttons.append(cancel_btn)
        panel.buttons(*buttons)
        return panel

    async def _on_expedition_start_confirm(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if not await self.db.spend_gold(gid, uid, formulas.EXPEDITION_START_COST):
            await interaction.response.edit_message(
                view=simple_panel(
                    f"Sending settlers out costs {formulas.EXPEDITION_START_COST:,} gold.",
                    accent=Palette.RED,
                )
            )
            return
        started = await self.db.start_expedition(gid, uid, time.time())
        if not started:
            await self.db.add_gold(gid, uid, formulas.EXPEDITION_START_COST)
            await interaction.response.edit_message(
                view=simple_panel("An expedition is already under way.", accent=Palette.RED)
            )
            return
        town = await self.db.get_town(gid, uid)
        perks = formulas.expedition_upgrade_perks(town["expedition_upgrades"])
        ready_at = int(time.time() + formulas.expedition_cooldown(perks))
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=180)
        panel.header(f"🧭 {_town_name(interaction.user.display_name)} · Expedition Begins")
        panel.text(
            f"Your settlers set out. First decision ready <t:{ready_at}:R> -- "
            "run `.expedition` again once it's time to choose."
        )
        await interaction.response.edit_message(view=panel)

    async def _build_expedition_choice_panel(
        self, gid: int, uid: int, expedition: dict, perks: list[str],
    ) -> Panel:
        user = await self.db.get_user(gid, uid)
        fame = formulas.reputation_fame(user["reputation"])
        fame_mult = formulas.fame_multiplier(fame) * formulas.expedition_reward_multiplier(perks)
        success_bonus = formulas.expedition_success_bonus(perks)
        legs = formulas.expedition_legs(perks)
        leg_num = expedition["legs_done"] + 1
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=120)
        panel.header(f"🧭 Expedition · Leg {leg_num}/{legs}")
        blocks = []
        for choice in EXPEDITION_CHOICES.values():
            lo, hi = choice["reward"]
            range_s = f"{round(lo * fame_mult):,}-{round(hi * fame_mult):,}"
            win_chance = min(0.97, choice["success"] + success_bonus)
            win_s = f"win {win_chance:.0%}"
            loss_lo, loss_hi = choice["loss"]
            lose_s = (
                f"risk losing {loss_lo:,}-{loss_hi:,} Population on a bad turn"
                if loss_hi else "a safe miss, nothing lost"
            )
            blocks.append(
                f"{choice['emoji']} **{choice['name']}** · {choice['risk']}\n"
                f"{chip((win_s, 8), (range_s, -12))} pop · *{lose_s}*"
            )
        panel.text("\n\n".join(blocks))
        footer = f"+{expedition['population_gained']:,} Population so far this trip"
        extras = []
        if fame > 0:
            extras.append(f"×{formulas.fame_multiplier(fame):.2f} from Fame")
        if "population" in perks:
            extras.append(f"×{1 + formulas.EXPEDITION_UPGRADE_POPULATION_BONUS:.2f} from upgrades")
        if extras:
            footer += " · " + " · ".join(extras)
        panel.footer(footer)
        buttons = []
        for key in EXPEDITION_CHOICE_ORDER:
            choice = EXPEDITION_CHOICES[key]
            btn = ui.Button(label=choice["name"], emoji=choice["emoji"], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_expedition_resolver(key)
            buttons.append(btn)
        panel.buttons(*buttons)
        return panel

    def _make_expedition_resolver(self, choice_key: str):
        async def resolver(interaction: discord.Interaction) -> None:
            await self._resolve_expedition_leg(interaction, choice_key)
        return resolver

    async def _resolve_expedition_leg(self, interaction: discord.Interaction, choice_key: str) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        expedition = await self.db.get_expedition(gid, uid)
        if expedition is None:
            await interaction.response.edit_message(
                view=simple_panel(
                    "No expedition under way. Run `.expedition` to start one.", accent=Palette.RED,
                )
            )
            return
        town = await self.db.get_town(gid, uid)
        perks = formulas.expedition_upgrade_perks(town["expedition_upgrades"])
        cooldown = formulas.expedition_cooldown(perks)
        legs = formulas.expedition_legs(perks)
        now = time.time()
        ready_at = expedition["last_choice_at"] + cooldown
        if now < ready_at:
            await interaction.response.edit_message(
                view=simple_panel(f"Too soon, ready <t:{int(ready_at)}:R>.", accent=Palette.RED)
            )
            return

        user = await self.db.get_user(gid, uid)
        fame = formulas.reputation_fame(user["reputation"])
        fame_mult = formulas.fame_multiplier(fame)
        reward_mult = formulas.expedition_reward_multiplier(perks)
        success_bonus = formulas.expedition_success_bonus(perks)
        choice = EXPEDITION_CHOICES[choice_key]
        success, delta = formulas.roll_expedition_leg(
            choice, fame_mult, reward_mult=reward_mult, success_bonus=success_bonus,
        )
        new_population = await self.db.add_population(gid, uid, delta)

        legs_done = expedition["legs_done"] + 1
        population_gained = max(0, expedition["population_gained"] + delta)
        concluded = legs_done >= legs
        if concluded:
            await self.db.clear_expedition(gid, uid)
        else:
            await self.db.advance_expedition(gid, uid, legs_done, population_gained, now)

        panel = Panel(accent=Palette.GREEN if success else Palette.RED, timeout=None)
        panel.header(f"{choice['emoji']} {choice['name']} · Leg {legs_done}/{legs}")
        if success:
            panel.text(f"✅ *{random.choice(choice['success_flavour'])}*")
            panel.text(f"🧑‍🤝‍🧑 {chip(('Gained', NAME_W), (f'+{delta:,}', -AMT_W))}")
        else:
            panel.text(f"❌ *{random.choice(choice['fail_flavour'])}*")
            if delta:
                panel.text(f"🧑‍🤝‍🧑 {chip(('Lost', NAME_W), (f'{delta:,}', -AMT_W))}")
            else:
                panel.text("🧑‍🤝‍🧑 Nothing lost, nothing gained.")

        if concluded:
            panel.footer(
                f"🏁 Expedition complete -- +{population_gained:,} Population this trip, "
                f"now {new_population:,} total. Run `.expedition` to send settlers out again."
            )
        else:
            ready = int(now + cooldown)
            panel.footer(
                f"+{population_gained:,} Population so far this trip, {new_population:,} total\n"
                f"next decision <t:{ready}:R>"
            )
        await interaction.response.edit_message(view=panel)

    # ── expedition upgrades: 4 permanent perks, one claimed per buy ──────

    async def _on_expedition_upgrade_open(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        panel = await self._build_expedition_upgrade_panel(gid, uid, interaction.user.display_name)
        await interaction.response.edit_message(view=panel)

    async def _build_expedition_upgrade_panel(self, gid: int, uid: int, display_name: str) -> Panel:
        town = await self.db.get_town(gid, uid)
        perks = formulas.expedition_upgrade_perks(town["expedition_upgrades"])
        user = await self.db.get_user(gid, uid)
        level = len(perks)
        panel = Panel(accent=Palette.GOLD, author_id=uid, timeout=60)
        panel.header(f"📈 {_town_name(display_name)} · Upgrade Expeditions")

        lines = []
        for key in EXPEDITION_UPGRADE_PERK_ORDER:
            perk = EXPEDITION_UPGRADE_PERKS[key]
            if key in perks:
                lines.append(f"✅ {perk['emoji']} **{perk['name']}** · {perk['effect']}")
            else:
                lines.append(f"⬜ {perk['emoji']} **{perk['name']}** · {perk['effect']}")
        panel.text("\n".join(lines))

        if level >= formulas.EXPEDITION_UPGRADE_MAX_LEVEL:
            panel.footer(f"All {formulas.EXPEDITION_UPGRADE_MAX_LEVEL} upgrades claimed. Your purse: {user['gold']:,} gold")
            back_btn = ui.Button(label="Back", style=discord.ButtonStyle.secondary)
            back_btn.callback = self._on_back_to_expedition
            panel.buttons(back_btn)
            return panel

        next_level = level + 1
        cost = formulas.expedition_upgrade_cost(next_level)
        panel.footer(
            f"Next upgrade (level {next_level}/{formulas.EXPEDITION_UPGRADE_MAX_LEVEL}): "
            f"{cost:,} gold -- pick which perk to claim.\nYour purse: {user['gold']:,} gold"
        )
        select = ui.Select(placeholder="📈 Choose a perk to claim…")
        for key in EXPEDITION_UPGRADE_PERK_ORDER:
            if key in perks:
                continue
            perk = EXPEDITION_UPGRADE_PERKS[key]
            select.add_option(
                label=f"{perk['name']} ({cost:,} gold)"[:100],
                value=key,
                emoji=perk["emoji"],
                description=perk["effect"][:100],
            )
        select.callback = self._on_expedition_perk_select
        panel.select(select)
        back_btn = ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._on_back_to_expedition
        panel.buttons(back_btn)
        return panel

    async def _on_expedition_perk_select(self, interaction: discord.Interaction) -> None:
        perk_key = interaction.data["values"][0]
        gid, uid = interaction.guild_id, interaction.user.id
        town = await self.db.get_town(gid, uid)
        perks = formulas.expedition_upgrade_perks(town["expedition_upgrades"])
        if perk_key in perks or len(perks) >= formulas.EXPEDITION_UPGRADE_MAX_LEVEL:
            await interaction.response.edit_message(
                view=simple_panel("That upgrade has already changed. Run `.expedition` again.", accent=Palette.RED)
            )
            return
        perk = EXPEDITION_UPGRADE_PERKS[perk_key]
        next_level = len(perks) + 1
        cost = formulas.expedition_upgrade_cost(next_level)
        user = await self.db.get_user(gid, uid)

        panel = Panel(accent=Palette.IRON, author_id=uid, timeout=60)
        panel.header(f"{perk['emoji']} Claim {perk['name']}?")
        panel.text(
            f"**{perk['effect']}**, permanently.\n\n"
            f"Cost: **{cost:,} gold** (upgrade {next_level}/{formulas.EXPEDITION_UPGRADE_MAX_LEVEL})\n"
            f"Your purse: {user['gold']:,} gold"
        )
        confirm_btn = ui.Button(label="Claim It", emoji="📈", style=discord.ButtonStyle.success)
        confirm_btn.callback = self._make_expedition_perk_confirm_handler(perk_key)
        cancel_btn = ui.Button(label="Back", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._on_expedition_upgrade_open
        panel.buttons(confirm_btn, cancel_btn)
        await interaction.response.edit_message(view=panel)

    def _make_expedition_perk_confirm_handler(self, perk_key: str):
        async def handler(interaction: discord.Interaction) -> None:
            gid, uid = interaction.guild_id, interaction.user.id
            town = await self.db.get_town(gid, uid)
            perks = formulas.expedition_upgrade_perks(town["expedition_upgrades"])
            if perk_key in perks or len(perks) >= formulas.EXPEDITION_UPGRADE_MAX_LEVEL:
                await interaction.response.edit_message(
                    view=simple_panel("That upgrade has already changed. Run `.expedition` again.", accent=Palette.RED)
                )
                return
            next_level = len(perks) + 1
            cost = formulas.expedition_upgrade_cost(next_level)
            if not await self.db.spend_gold(gid, uid, cost):
                await interaction.response.edit_message(
                    view=simple_panel(f"That upgrade costs {cost:,} gold.", accent=Palette.RED)
                )
                return
            perks.append(perk_key)
            await self.db.set_expedition_upgrades(gid, uid, ",".join(perks))

            perk = EXPEDITION_UPGRADE_PERKS[perk_key]
            panel = Panel(accent=Palette.GREEN, timeout=None)
            panel.header(f"{perk['emoji']} {perk['name']} claimed!")
            panel.text(f"**{perk['effect']}**, from now on.")
            panel.footer(f"Expedition upgrade {next_level}/{formulas.EXPEDITION_UPGRADE_MAX_LEVEL}")
            back_btn = ui.Button(label="Back to Expedition", emoji="🧭", style=discord.ButtonStyle.secondary)
            back_btn.callback = self._on_back_to_expedition
            panel.buttons(back_btn)
            await interaction.response.edit_message(view=panel)
        return handler

    async def _on_back_to_expedition(self, interaction: discord.Interaction) -> None:
        panel = await self._build_expedition_panel(
            interaction.guild_id, interaction.user.id, interaction.user.display_name
        )
        await interaction.response.edit_message(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Town(bot))
