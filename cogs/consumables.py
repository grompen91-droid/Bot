"""Consumables: using potions/foods for temporary buffs, and checking
what's currently active. See econ/data/consumables.py for the registry
and econ/buffs.py for how the buffs get applied elsewhere.
"""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from econ.buffs import extend_expiry
from econ.data.consumables import CONSUMABLES
from econ.data.items import ITEMS, item_label
from ui.panels import NAME_W, Palette, Panel, chip, simple_panel


class Consumables(commands.Cog):
    """Potions and foods: drink or eat them for a while-it-lasts edge."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    async def _use_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        rows = await self.db.get_inventory(interaction.guild_id, interaction.user.id)
        q = current.lower()
        return [
            app_commands.Choice(
                name=f"{ITEMS[row['item']]['name']} ({row['qty']})", value=row["item"]
            )
            for row in rows
            if row["item"] in CONSUMABLES and q in ITEMS[row["item"]]["name"].lower()
        ][:25]

    @commands.hybrid_command(name="use", description="Use a consumable for its buff")
    @commands.guild_only()
    @app_commands.describe(item="The potion or food to use")
    @app_commands.autocomplete(item=_use_autocomplete)
    async def use(self, ctx: commands.Context, *, item: str):
        gid, uid = ctx.guild.id, ctx.author.id
        q = item.strip().lower().replace(" ", "_")
        item_key = q if q in CONSUMABLES else next(
            (k for k in CONSUMABLES if ITEMS[k]["name"].lower() == item.strip().lower()),
            None,
        )
        if item_key is None:
            await ctx.send(
                view=simple_panel(
                    f"**{item}** isn't a usable consumable. Check `.inventory` "
                    "under the ✨ Consumables tab.",
                    accent=Palette.RED,
                ),
                ephemeral=True,
            )
            return

        have = await self.db.get_item_qty(gid, uid, item_key)
        if have <= 0:
            await ctx.send(
                view=simple_panel(
                    f"You carry no {item_label(item_key)}.", accent=Palette.RED
                ),
                ephemeral=True,
            )
            return

        buff = CONSUMABLES[item_key]
        now = time.time()
        active = await self.db.get_active_buffs(gid, uid, now)
        current_expiry = next(
            (r["expires_at"] for r in active if r["item"] == item_key), None
        )
        was_active = current_expiry is not None
        expires_at = extend_expiry(current_expiry, item_key, now)
        capped = was_active and expires_at < current_expiry + buff["duration"]

        if not await self.db.remove_item(gid, uid, item_key, 1):
            await ctx.send(
                view=simple_panel(
                    f"You carry no {item_label(item_key)}.", accent=Palette.RED
                ),
                ephemeral=True,
            )
            return
        await self.db.add_buff(gid, uid, item_key, expires_at)

        panel = Panel(accent=Palette.GREEN, timeout=None)
        panel.header(f"{ITEMS[item_key]['emoji']} {ITEMS[item_key]['name']} Used")
        panel.text(f"✨ {buff['description']}")
        footer = f"{'extended to' if was_active else 'active until'} <t:{int(expires_at)}:R> · see `.buffs`"
        if capped:
            footer += " · maxed out, using another won't extend it further"
        panel.footer(footer)
        await ctx.send(view=panel)

    @commands.hybrid_command(name="buffs", description="See currently active buffs")
    @commands.guild_only()
    @app_commands.describe(member="Whose active buffs to check (default: you)")
    async def buffs(
        self, ctx: commands.Context, member: discord.Member | None = None
    ):
        target = member or ctx.author
        rows = await self.db.get_active_buffs(ctx.guild.id, target.id, time.time())

        panel = Panel(timeout=None)
        panel.header(f"✨ {target.display_name}'s Active Buffs")
        if not rows:
            panel.text("*Nothing active. Use a potion or food with `.use`.*")
        else:
            rows = sorted(rows, key=lambda r: r["expires_at"])
            lines = []
            for row in rows:
                info = CONSUMABLES.get(row["item"])
                if not info:
                    continue
                item_info = ITEMS[row["item"]]
                lines.append(
                    f"{item_info['emoji']} "
                    f"{chip((item_info['name'], NAME_W))} "
                    f"{info['description']} · <t:{int(row['expires_at'])}:R>"
                )
            panel.text("\n".join(lines))
        await ctx.send(view=panel)


async def setup(bot: commands.Bot):
    await bot.add_cog(Consumables(bot))
