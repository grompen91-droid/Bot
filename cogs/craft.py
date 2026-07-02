"""Crafting: combine gathered goods into a single, higher-value item.
A standalone skill (not tied to any trade), levelled by crafting
itself and gating which recipes you can attempt. Anyone can craft
regardless of their current job.
"""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from econ import formulas
from econ.buffs import (
    active_buff_summary,
    active_buff_totals,
    apply_cooldown_buff,
    apply_xp_buff,
)
from econ.data.consumables import CONSUMABLES
from econ.data.items import ITEMS
from econ.data.recipes import RECIPES, resolve_recipe
from ui.panels import AMT_W, NAME_W, QTY_W, Palette, Panel, chip, simple_panel

CRAFTING_SKILL = "crafting"

RECIPE_CHOICES = [
    app_commands.Choice(name=f"{ITEMS[r['output_item']]['emoji']} {r['name']}", value=key)
    for key, r in RECIPES.items()
]


class Craft(commands.Cog):
    """The workbench: turn goods into something worth more."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @commands.hybrid_command(name="recipes", description="See what you can craft")
    @commands.guild_only()
    async def recipes(self, ctx: commands.Context):
        gid, uid = ctx.guild.id, ctx.author.id
        # Read-only: peeking must never create a phantom Crafting skill
        # row for a player who has never crafted, same bug .job info
        # had before peek_skill existed.
        skill = await self.db.peek_skill(gid, uid, CRAFTING_SKILL)
        level = skill["level"]

        panel = Panel(accent=Palette.BLUE, timeout=None)
        panel.header("🛠️ Recipes")
        lines = []
        for r in sorted(RECIPES.values(), key=lambda r: r["unlock_level"]):
            out = ITEMS[r["output_item"]]
            locked = level < r["unlock_level"]
            status = "🔒" if locked else "✅"
            ing_text = " · ".join(
                f"{ITEMS[i]['emoji']} x{q}" for i, q in r["ingredients"]
            )
            buff = CONSUMABLES.get(r["output_item"])
            yield_text = (
                f"✨ {buff['description']}"
                if buff
                else f"worth ~{formulas.fmt_gold(out['value'])}"
            )
            lines.append(
                f"{status} {out['emoji']} **{r['name']}** (Lv {r['unlock_level']})\n"
                f"　needs {ing_text} · yields the item · {yield_text}"
            )
        panel.text("\n\n".join(lines))
        panel.footer(
            f"🛠️ Crafting Lv {level} · craft with .craft <recipe> · "
            "you get the item itself, not gold"
        )
        await ctx.send(view=panel)

    @commands.hybrid_command(
        name="craft", description="Craft an item from a recipe using gathered goods"
    )
    @commands.guild_only()
    @app_commands.describe(recipe="The recipe to craft")
    @app_commands.choices(recipe=RECIPE_CHOICES)
    async def craft(self, ctx: commands.Context, *, recipe: str):
        gid, uid = ctx.guild.id, ctx.author.id
        recipe_key = resolve_recipe(recipe)
        if recipe_key is None:
            await ctx.send(
                view=simple_panel(
                    f"No recipe known as **{recipe}**. See `.recipes`.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return
        r = RECIPES[recipe_key]

        skill = await self.db.peek_skill(gid, uid, CRAFTING_SKILL)
        buffs = await active_buff_totals(self.db, gid, uid)
        if skill["level"] < r["unlock_level"]:
            await ctx.send(
                view=simple_panel(
                    f"🔒 You need Crafting level **{r['unlock_level']}** to craft "
                    f"**{r['name']}** (you're level {skill['level']}). "
                    "Craft simpler recipes to get there.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        now = time.time()
        cooldown = apply_cooldown_buff(
            formulas.effective_cooldown(formulas.CRAFTING_COOLDOWN, skill["level"]), buffs
        )
        ready_at = skill["last_work"] + cooldown
        if now < ready_at:
            await ctx.send(
                view=simple_panel(
                    f"🛠️ Your hands are still busy. Ready <t:{int(ready_at)}:R>.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        missing = []
        for item, qty in r["ingredients"]:
            have = await self.db.get_item_qty(gid, uid, item)
            if have < qty:
                missing.append(f"{ITEMS[item]['emoji']} {ITEMS[item]['name']} ({have}/{qty})")
        if missing:
            await ctx.send(
                view=simple_panel(
                    f"🛠️ Not enough materials for **{r['name']}**: " + ", ".join(missing),
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        for item, qty in r["ingredients"]:
            await self.db.remove_item(gid, uid, item, qty)
        # Only now do we persist a real skill row -- a rejected attempt
        # above must never inflate total_level with a phantom row.
        await self.db.get_skill(gid, uid, CRAFTING_SKILL)
        xp_gain = round(apply_xp_buff(formulas.roll_work_xp(formulas.CRAFTING_COOLDOWN), buffs))
        new_level, new_xp, levels_gained = formulas.apply_xp(
            skill["level"], skill["xp"], xp_gain
        )
        await self.db.update_skill(gid, uid, CRAFTING_SKILL, new_level, new_xp, now)
        await self.db.add_item(gid, uid, r["output_item"], 1)
        await self.db.incr_stat(gid, uid, "items_crafted")

        out = ITEMS[r["output_item"]]
        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header(f"🛠️ {r['name']} Crafted!")
        ing_lines = "\n".join(
            f"{ITEMS[i]['emoji']} {chip((ITEMS[i]['name'], NAME_W), (f'-{q}', -QTY_W))}"
            for i, q in r["ingredients"]
        )
        panel.text(ing_lines)
        buff = CONSUMABLES.get(r["output_item"])
        flavour = f"✨ {buff['description']}" if buff else f"worth ~{formulas.fmt_gold(out['value'])}"
        panel.text(
            f"{out['emoji']} {chip((out['name'], NAME_W), ('+1', -QTY_W))} *({flavour})*"
        )
        if buff:
            panel.text("*usable with `.use`*")

        if levels_gained:
            panel.text(f"⭐ **Level up!** Crafting is now level **{new_level}**")

        needed = formulas.xp_to_next(new_level)
        ready = int(
            now + apply_cooldown_buff(
                formulas.effective_cooldown(formulas.CRAFTING_COOLDOWN, new_level), buffs
            )
        )
        footer = (
            f"+{xp_gain} XP · Lv {new_level} `{formulas.progress_bar(new_xp, needed)}` "
            f"{new_xp}/{needed}\nready <t:{ready}:R>"
        )
        buff_line = active_buff_summary(buffs)
        if buff_line:
            footer += f"\n✨ active: {buff_line}"
        panel.footer(footer)
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Craft(bot))
