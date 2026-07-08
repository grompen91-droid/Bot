"""Help and lore."""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from econ import formulas
from econ.buffs import active_buff_summary, active_buff_totals, apply_cooldown_buff
from econ.data.caravans import CARAVAN_ROUTES
from econ.data.consumables import CONSUMABLES, WORK_DROP_CONSUMABLES
from econ.data.items import ITEMS, RARITIES
from econ.data.jobs import JOBS, MAX_JOB_UNLOCK_LEVEL
from econ.data.materials import MATERIAL_GROUPS, MATERIAL_SUPPLY_MAX_RARITY_ORDER, MATERIALS
from econ.data.minigames import MINIGAMES
from econ.data.recipes import RECIPES
from econ.data.store import STORE_POOL
from econ.data.town_buildings import (
    MAX_BUILDING_TIER,
    TOWN_BUILDINGS,
    building_tier_price,
    town_hall_material,
)
from econ.data.town_workers import (
    MAX_WORKER_TIER,
    TOWN_WORKERS,
    worker_tier_price,
    workers_for_building,
)
from ui.panels import NAME_W, Palette, Panel, chip, simple_panel

# Cross-cog resolvers `.info` dispatches through -- no cycle, since
# neither cog imports this one back.
from cogs.jobs import resolve_skill_key
from cogs.market import resolve_item
from cogs.town import resolve_building, resolve_worker

# Each section is a list of command names; .help renders them as
# clickable slash-command mentions (</name:id>) when the bot has cached
# the ids at sync (see MedievalBot._build_command_mentions), else as
# plain ".name" text. Names must match the registered slash command
# names so the lookup resolves.
HELP_SECTIONS = [
    ("⚒️ Trade", ["job", "work", "skills"]),
    ("🏪 Market", ["inventory", "market", "sell", "shop", "buy"]),
    ("🛠️ Crafting", ["recipes", "craft"]),
    ("✨ Consumables", ["use", "buffs"]),
    ("🗺️ Venture", ["venture"]),
    ("💰 Gold", ["balance", "daily", "beg", "pay", "profile", "theme", "leaderboard"]),
    ("🏦 Bank", ["bank", "deposit", "withdraw"]),
    ("🗡️ Crime", ["pickpocket", "smuggle", "surrender"]),
    # Every job-specific minigame lives in this one section, not a new
    # section per job, however many of these exist.
    (
        "🎯 Job Minigames",
        ["harvest", "dig", "fish", "fell", "hunt", "bake", "tend",
         "stretch", "facet", "brew", "rob"],
    ),
    # The mid-game settlement: .study/.patrol only do anything once
    # their building is built, same "always listed, gated at runtime"
    # treatment as .pickpocket/.smuggle above.
    (
        "🏰 Town",
        ["townhall", "town", "buildings", "workers", "fire", "supply", "collect",
         "gather", "scavenge", "study", "patrol", "caravan", "expedition"],
    ),
    ("📖 Lookup", ["info"]),
]

# .pickpocket, .smuggle, and .rob all share the same "current Criminal,
# or Criminal skill level 5+" access rule as every other minigame.
CRIME_MIN_LEVEL_WITHOUT_JOB = formulas.MINIGAME_MIN_LEVEL_WITHOUT_JOB


class Info(commands.Cog):
    """Guidance for new townsfolk."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    def _cmd(self, name: str) -> str:
        """A command's clickable slash mention if cached, else plain
        ".name" text (prefix commands still work either way)."""
        return getattr(self.bot, "command_mentions", {}).get(name, f"`.{name}`")

    @commands.hybrid_command(name="help", description="A guide to life in the town")
    async def help(self, ctx: commands.Context):
        town_founded = False
        if ctx.guild is not None:
            town = await self.db.get_town(ctx.guild.id, ctx.author.id)
            town_founded = town["hall_level"] > 0

        panel = Panel(timeout=None)
        panel.header("📜 Commands")
        for title, names in HELP_SECTIONS:
            if title == "🏰 Town" and not town_founded:
                # .townhall is the only door in until it's actually founded --
                # the rest only mean anything once there's a town to run.
                names = ["townhall"]
            panel.field(title, " · ".join(self._cmd(n) for n in names))
        panel.field(
            "⏳ Cooldowns",
            f"{self._cmd('cd')} · see every timer you're carrying, at a glance",
        )
        panel.footer("tap any command to run it · all work as .prefix too")
        await ctx.send(view=panel)

    @commands.hybrid_command(name="about", description="About this humble town")
    async def about(self, ctx: commands.Context):
        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header("🏰 About the Town")
        panel.text(
            f"{len(JOBS)} trades · {len(ITEMS)} goods · {len(RECIPES)} recipes · "
            "daily-shifting market. No Discord roles, your rank is gold and "
            "skill alone. Walk an honest trade and build fame, or turn to "
            "crime and build infamy, but get caught robbing the bank and "
            "it's gone.\n\n"
            f"Once you've made your fortune, `.townhall` founds your own "
            f"settlement -- {len(TOWN_BUILDINGS)} buildings, {len(TOWN_WORKERS)} "
            "hireable workers, and a hundred construction materials to spend."
        )
        await ctx.send(view=panel)

    # ══════════════════════════════ .info ═══════════════════════════════
    # One universal lookup. Resolves the query against commands, trades,
    # items/materials, buildings, workers, then recipes, in that order --
    # first match wins (each registry's own resolve_* already fuzzy-
    # matches key or display name, so this doesn't reinvent that).

    @commands.hybrid_command(
        name="info", description="Look up an item, trade, building, worker, recipe, or command",
    )
    @app_commands.describe(query="What to look up, e.g. 'rubble', 'farmer', 'quarry', '.work'")
    async def info(self, ctx: commands.Context, *, query: str):
        panel = self._resolve_info_panel(query)
        if panel is None:
            await ctx.send(
                view=simple_panel(f"Nothing in the town archives matches **{query}**.", accent=Palette.RED),
                ephemeral=True,
            )
            return
        await ctx.send(view=panel)

    def _resolve_info_panel(self, query: str) -> Panel | None:
        cmd = self.bot.get_command(query.strip().lstrip("."))
        if cmd is not None:
            return self._info_command_panel(cmd)
        job_key = resolve_skill_key(query)
        if job_key is not None:
            return self._info_job_panel(job_key)
        item_key = resolve_item(query)
        if item_key is not None:
            return self._info_item_panel(item_key)
        building_key = resolve_building(query)
        if building_key is not None:
            return self._info_building_panel(building_key)
        worker_key = resolve_worker(query)
        if worker_key is not None:
            return self._info_worker_panel(worker_key)
        return None

    def _info_command_panel(self, cmd) -> Panel:
        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header(f"📜 {self._cmd(cmd.qualified_name)}")
        panel.text(cmd.description or "*No description set.*")
        return panel

    def _info_job_panel(self, job_key: str) -> Panel:
        panel = Panel(accent=Palette.BLUE, timeout=None)
        if job_key == "crafting":
            panel.header("🛠️ Crafting")
            panel.text(
                "A standalone skill, not tied to any trade -- anyone can craft "
                "regardless of their current job.\n`.recipes` to browse what's "
                "unlocked · `.craft <recipe>` to make one."
            )
            return panel
        info = JOBS[job_key]
        panel.header(f"{info['emoji']} {info['name']}")
        unlock = info["unlock_total_level"]
        lines = ["Open from the start." if not unlock else f"Unlocks at **{unlock} total skill level**."]
        lines.append(f"`.job choose {job_key}` to take it up · `.job info {job_key}` for its full yield table.")
        if job_key in MINIGAMES:
            lines.append(f"`.{MINIGAMES[job_key]['command']}` for its minigame.")
        panel.text("\n".join(lines))
        return panel

    def _item_sources(self, item_key: str) -> list[str]:
        """Every way `.info` knows of to actually get this item."""
        sources = []
        for info in JOBS.values():
            if any(item_key == entry[0] for entry in info["yields"]):
                sources.append(f"`.work` as {info['emoji']} {info['name']}")
        if item_key in WORK_DROP_CONSUMABLES:
            sources.append("a rare find from any `.work`, regardless of trade")
        for group, keys in MATERIAL_GROUPS.items():
            if item_key not in keys:
                continue
            if group == "universal":
                rarity_order = list(RARITIES.keys()).index(ITEMS[item_key]["rarity"])
                if rarity_order > MATERIAL_SUPPLY_MAX_RARITY_ORDER:
                    sources.append(f"`.scavenge {ITEMS[item_key]['name']}`, once Town Hall is high enough level")
                sources.append("a lucky find from any `.work` (rarity improves with total skill)")
            else:
                building = TOWN_BUILDINGS[group]
                index = keys.index(item_key)
                tier = index // 2 + 1
                if index % 2 == 0:
                    # Slot 0 -- the building's OWN material at this tier:
                    # produced passively once built, and .gather always
                    # pays out in this slot (plus a chance at the next
                    # tier's, on a flawless run).
                    sources.append(f"{building['name']}'s Tier {tier} output, once built")
                    sources.append(f"`.gather {group}` at Tier {tier}+")
                else:
                    # Slot 1 -- a linked WORKER's upgrade material only.
                    # .gather/passive trickle never produce this slot;
                    # `.scavenge` is the only route once it's rare+.
                    worker_names = [TOWN_WORKERS[w]["name"] for w in workers_for_building(group)]
                    workers_str = " / ".join(worker_names)
                    sources.append(f"{workers_str}'s Tier {tier} upgrade cost, not produced by {building['name']} itself")
                    rarity_order = list(RARITIES.keys()).index(ITEMS[item_key]["rarity"])
                    if rarity_order > MATERIAL_SUPPLY_MAX_RARITY_ORDER:
                        sources.append(f"`.scavenge {ITEMS[item_key]['name']}`, once Town Hall is high enough level")
        for r in RECIPES.values():
            if r["output_item"] == item_key:
                ing_str = ", ".join(f"{qty}x {ITEMS[i]['name']}" for i, qty in r["ingredients"])
                sources.append(f"`.craft {r['name']}` (needs {ing_str}, Crafting lv {r['unlock_level']})")
        if item_key in STORE_POOL:
            sources.append("sometimes stocked at `.shop`")
        if item_key in MATERIALS:
            rarity_order = list(RARITIES.keys()).index(ITEMS[item_key]["rarity"])
            if rarity_order <= MATERIAL_SUPPLY_MAX_RARITY_ORDER:
                sources.append("`.supply`")
        return sources

    def _item_uses(self, item_key: str) -> list[str]:
        """Every way `.info` knows of to actually spend this item."""
        uses = []
        if item_key in CONSUMABLES:
            c = CONSUMABLES[item_key]
            uses.append(f"✨ {c['description']} -- usable with `.use`")
        ingredient_of = sorted({
            r["name"] for r in RECIPES.values()
            if any(i == item_key for i, _qty in r["ingredients"])
        })
        if ingredient_of:
            uses.append("Crafting ingredient for: " + ", ".join(ingredient_of))
        building_uses = sorted({
            b["name"] for b in TOWN_BUILDINGS.values()
            if any(item_key in mats for _gold, mats in b["tiers"])
        })
        if building_uses:
            uses.append("Building upgrade cost for: " + ", ".join(building_uses))
        worker_uses = sorted({
            w["name"] for w in TOWN_WORKERS.values()
            if any(item_key in mats for _gold, mats in w["tiers"])
        })
        if worker_uses:
            uses.append("Worker upgrade cost for: " + ", ".join(worker_uses))
        if any(
            item_key == town_hall_material(lvl)
            for lvl in range(2, formulas.TOWN_HALL_MAX_LEVEL + 1)
        ):
            uses.append("Town Hall upgrade cost")
        # `.market` only ever LISTS a trade's own yields and crafted-goods
        # output -- materials (and shop-only consumables) never show up
        # there to browse, even though `.sell` still works on them.
        in_market = any(
            item_key == entry[0] for info in JOBS.values() for entry in info["yields"]
        ) or any(r["output_item"] == item_key for r in RECIPES.values())
        if in_market:
            uses.append(f"Sells for {ITEMS[item_key]['value']:,} gold via `.sell` (see today's price at `.market`)")
        else:
            uses.append(f"Sells for {ITEMS[item_key]['value']:,} gold via `.sell` (price drifts daily)")
        return uses

    def _info_item_panel(self, item_key: str) -> Panel:
        info = ITEMS[item_key]
        rarity = RARITIES[info["rarity"]]
        panel = Panel(accent=Palette.GOLD, timeout=None)
        panel.header(f"{info['emoji']} {info['name']}")
        panel.text(f"{rarity['badge']} {rarity['name']} · worth {info['value']:,} gold")

        panel.divider()
        panel.subheader("📍 Where to get it")
        sources = self._item_sources(item_key)
        panel.text(
            "\n".join(f"- {s}" for s in sources) if sources
            else "*Not obtained directly -- check crafting or a lucky drop.*"
        )

        panel.divider()
        panel.subheader("🔧 What it's for")
        panel.text("\n".join(f"- {u}" for u in self._item_uses(item_key)))
        return panel

    def _info_building_panel(self, key: str) -> Panel:
        info = TOWN_BUILDINGS[key]
        panel = Panel(accent=Palette.IRON, timeout=None)
        panel.header(f"{info['emoji']} {info['name']}")
        panel.text(
            f"*{info['flavor']}*\nUnlocks at Town Hall level **{info['unlock_hall_level']}**. "
            "`.buildings` to build or upgrade it."
        )
        panel.divider()
        panel.subheader("💰 Tier costs")
        lines = []
        for tier in range(1, MAX_BUILDING_TIER + 1):
            gold, mats = building_tier_price(key, tier)
            mat_str = ", ".join(f"{qty}x {ITEMS[m]['name']}" for m, qty in mats.items())
            lines.append(f"Tier {tier}: {gold:,} gold + {mat_str}")
        panel.text("\n".join(lines))
        linked = workers_for_building(key)
        if linked:
            panel.footer("Workers: " + ", ".join(TOWN_WORKERS[w]["name"] for w in linked))
        return panel

    def _info_worker_panel(self, key: str) -> Panel:
        info = TOWN_WORKERS[key]
        building = TOWN_BUILDINGS[info["linked"]]
        panel = Panel(accent=Palette.IRON, timeout=None)
        panel.header(f"{info['emoji']} {info['name']}")
        panel.text(
            f"*{info['flavor']}*\nBoosts **{building['name']}**. `.workers` to hire or "
            "train them (needs a Workers' Lodge built), `.fire` to dismiss."
        )
        panel.divider()
        panel.subheader("💰 Tier costs")
        lines = []
        for tier in range(1, MAX_WORKER_TIER + 1):
            gold, mats = worker_tier_price(key, tier)
            mat_str = ", ".join(f"{qty}x {ITEMS[m]['name']}" for m, qty in mats.items())
            lines.append(f"Tier {tier}: {gold:,} gold + {mat_str}")
        panel.text("\n".join(lines))
        return panel

    @commands.hybrid_command(
        name="cd", aliases=["cooldown", "cooldowns"],
        description="See every cooldown someone is currently carrying",
    )
    @commands.guild_only()
    @app_commands.describe(member="Whose cooldowns to check (default: you)")
    async def cooldowns(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        gid, uid = ctx.guild.id, target.id
        user = await self.db.get_user(gid, uid)
        skills = {s["job"]: s for s in await self.db.get_all_skills(gid, uid)}
        mg_last = await self.db.get_minigame_cooldowns(gid, uid)
        now = time.time()
        # Every cooldown below is read through the same buff totals the
        # actual commands apply (see econ/buffs.py), so the countdowns
        # shown here always match what running the command would do.
        buffs = await active_buff_totals(self.db, gid, uid)

        def status(ready_at: float) -> str:
            return "✅ ready now" if now >= ready_at else f"<t:{int(ready_at)}:R>"

        def skill_level(job_key: str) -> int:
            row = skills.get(job_key)
            return row["level"] if row else 0

        # Grouped the same way .help sections its commands, so the two
        # screens read as one system.
        trade_lines = []
        venture_lines = []
        gold_lines = []
        crime_lines = []
        minigame_lines = []
        town_lines = []

        if user["job"]:
            job_info = JOBS[user["job"]]
            skill = skills.get(user["job"])
            level = skill["level"] if skill else 1
            last_work = skill["last_work"] if skill else 0
            cooldown = apply_cooldown_buff(
                formulas.effective_cooldown(job_info["cooldown"], level), buffs
            )
            trade_lines.append(
                f"{job_info['emoji']} {chip(('.work', NAME_W))} {status(last_work + cooldown)}"
            )
        else:
            trade_lines.append(f"⚒️ {chip(('.work', NAME_W))} *(take a trade with `.job` first)*")

        craft_skill = skills.get("crafting")
        craft_level = craft_skill["level"] if craft_skill else 1
        craft_last = craft_skill["last_work"] if craft_skill else 0
        craft_cooldown = apply_cooldown_buff(
            formulas.effective_cooldown(formulas.CRAFTING_COOLDOWN, craft_level), buffs
        )
        trade_lines.append(
            f"🛠️ {chip(('.craft', NAME_W))} {status(craft_last + craft_cooldown)}"
        )

        trade_lines.append(
            f"🪧 {chip(('.job choose', NAME_W))} "
            f"{status(user['last_job_switch'] + formulas.JOB_SWITCH_COOLDOWN)}"
        )
        venture_lines.append(
            f"🗺️ {chip(('.venture', NAME_W))} "
            f"{status(user['last_venture'] + apply_cooldown_buff(formulas.VENTURE_COOLDOWN, buffs))}"
        )

        # Same UTC clock .daily itself uses.
        today = datetime.now(timezone.utc).date()
        if user["last_daily"] == today.isoformat():
            reset_at = datetime.combine(
                today + timedelta(days=1), dtime.min, tzinfo=timezone.utc
            )
            daily_status = f"<t:{int(reset_at.timestamp())}:R>"
        else:
            daily_status = "✅ ready now"
        gold_lines.append(f"🕯️ {chip(('.daily', NAME_W))} {daily_status}")

        gold_lines.append(
            f"🥺 {chip(('.beg', NAME_W))} "
            f"{status(mg_last.get('beg', 0.0) + apply_cooldown_buff(formulas.BEG_COOLDOWN, buffs))}"
        )

        crime_access = (
            user["job"] == "criminal"
            or skill_level("criminal") >= CRIME_MIN_LEVEL_WITHOUT_JOB
        )
        if crime_access:
            crime_lines.append(
                f"🗡️ {chip(('.pickpocket', NAME_W))} "
                f"{status(user['last_pickpocket'] + apply_cooldown_buff(formulas.PICKPOCKET_COOLDOWN, buffs))}"
            )
            crime_lines.append(
                f"🚚 {chip(('.smuggle', NAME_W))} "
                f"{status(mg_last.get('smuggle', 0.0) + apply_cooldown_buff(formulas.SMUGGLE_COOLDOWN, buffs))}"
            )
            crime_lines.append(
                f"🏦 {chip(('.rob', NAME_W))} "
                f"{status(mg_last.get('criminal', 0.0) + apply_cooldown_buff(MINIGAMES['criminal']['cooldown'], buffs))}"
            )

        if user["job"] == "alchemist" or skill_level("alchemist") >= formulas.BREW_MIN_LEVEL_WITHOUT_JOB:
            minigame_lines.append(
                f"🧪 {chip(('.brew', NAME_W))} "
                f"{status(user['last_brew'] + apply_cooldown_buff(formulas.BREW_COOLDOWN, buffs))}"
            )

        for job_key, config in MINIGAMES.items():
            if job_key == "criminal":
                continue  # already shown above as .rob
            eligible = (
                user["job"] == job_key
                or skill_level(job_key) >= formulas.MINIGAME_MIN_LEVEL_WITHOUT_JOB
            )
            if not eligible:
                continue
            cooldown = apply_cooldown_buff(
                formulas.minigame_cooldown(
                    JOBS[job_key]["unlock_total_level"], MAX_JOB_UNLOCK_LEVEL
                ),
                buffs,
            )
            command_label = f".{config['command']}"
            minigame_lines.append(
                f"{JOBS[job_key]['emoji']} {chip((command_label, NAME_W))} "
                f"{status(mg_last.get(job_key, 0.0) + cooldown)}"
            )

        # .gather has its own cooldown per built production building --
        # only shows the ones you actually have. Shown as its ".g"
        # alias with a wider column than NAME_W's usual 16: the longest
        # building keys (masons_workshop, gem_cutters_den) plus
        # ".gather " wouldn't fit without truncating past readability.
        for row in await self.db.get_all_buildings(gid, uid):
            building_key = row["building"]
            info_b = TOWN_BUILDINGS.get(building_key)
            if not info_b or info_b["kind"] != "production":
                continue
            command_label = f".g {building_key}"
            town_lines.append(
                f"{info_b['emoji']} {chip((command_label, 18))} "
                f"{status(mg_last.get(f'gather_{building_key}', 0.0) + formulas.GATHER_COOLDOWN)}"
            )

        # .study/.patrol/.scavenge stay hidden until they actually apply
        # (their building built, or a town founded at all), same rule as
        # .brew staying hidden pre-Alchemist above.
        town = await self.db.get_town(gid, uid)
        if town["hall_level"] > 0:
            town_lines.append(
                f"🧰 {chip(('.scavenge', NAME_W))} "
                f"{status(mg_last.get('scavenge', 0.0) + formulas.SCAVENGE_COOLDOWN)}"
            )
        if await self.db.get_building_tier(gid, uid, "great_library") > 0:
            town_lines.append(
                f"📚 {chip(('.study', NAME_W))} "
                f"{status(mg_last.get('study', 0.0) + formulas.STUDY_COOLDOWN)}"
            )
        if await self.db.get_building_tier(gid, uid, "watchtower") > 0:
            town_lines.append(
                f"🗼 {chip(('.patrol', NAME_W))} "
                f"{status(mg_last.get('patrol', 0.0) + formulas.PATROL_COOLDOWN)}"
            )

        # .caravan/.expedition aren't cooldowns so much as "is one
        # already under way" -- same "hidden until it applies to you"
        # rule, gated on founding.
        if town["hall_level"] > 0:
            active_caravan = await self.db.get_caravan(gid, uid)
            if active_caravan is not None:
                route = CARAVAN_ROUTES[active_caravan["route"]]
                ready_at = formulas.caravan_ready_at(active_caravan["departed_at"], route["duration_hours"])
                town_lines.append(f"🐎 {chip(('.caravan', NAME_W))} {status(ready_at)}")
            else:
                town_lines.append(f"🐎 {chip(('.caravan', NAME_W))} ✅ ready to send")

            active_expedition = await self.db.get_expedition(gid, uid)
            if active_expedition is not None:
                perks = formulas.expedition_upgrade_perks(town["expedition_upgrades"])
                ready_at = active_expedition["last_choice_at"] + formulas.expedition_cooldown(perks)
                town_lines.append(f"🧭 {chip(('.expedition', NAME_W))} {status(ready_at)}")
            else:
                town_lines.append(f"🧭 {chip(('.expedition', NAME_W))} ✅ ready to send")

        panel = Panel(timeout=None)
        panel.header(f"⏳ {target.display_name}'s Cooldowns")
        sections = [
            ("⚒️ Trade", trade_lines),
            ("🗺️ Venture", venture_lines),
            ("💰 Gold", gold_lines),
            ("🗡️ Crime", crime_lines),
            ("🎯 Job Minigames", minigame_lines),
            ("🏰 Town", town_lines),
        ]
        first = True
        for title, section_lines in sections:
            if not section_lines:
                continue
            if not first:
                panel.divider()
            first = False
            panel.subheader(title)
            panel.text("\n".join(section_lines))
        buff_line = active_buff_summary(buffs)
        if buff_line:
            panel.footer(f"✨ active: {buff_line}")
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))
