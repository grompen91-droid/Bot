"""Components V2 building blocks with a medieval look.

Every reply the bot sends is a `Panel`, a LayoutView wrapping one
accent-coloured Container. The fluent builder keeps cogs short:

    panel = Panel(accent=Palette.GOLD)
    panel.header("🏰 The Town Square")
    panel.text("Welcome, traveller.")
    panel.divider()
    panel.footer("coin for the coffers")
"""

from __future__ import annotations

import discord
from discord import ui


class Palette:
    """Accent colours for panel edges."""

    GOLD = discord.Colour(0xC9A227)       # default parchment-and-gold
    GREEN = discord.Colour(0x4E7A27)      # success / harvest
    RED = discord.Colour(0x8C2B2B)        # failure / warning
    BLUE = discord.Colour(0x2B5B8C)       # info / skills
    PURPLE = discord.Colour(0x6B3FA0)     # rare finds / level ups
    IRON = discord.Colour(0x5A5A5A)       # the smithy


class Panel(ui.LayoutView):
    """One medieval-styled Components V2 container with fluent helpers."""

    def __init__(
        self,
        *,
        accent: discord.Colour = Palette.GOLD,
        timeout: float | None = 180,
        author_id: int | None = None,
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.container = ui.Container(accent_colour=accent)
        self.add_item(self.container)

    # ── building blocks ─────────────────────────────────────────────────

    def header(self, text: str) -> Panel:
        self.container.add_item(ui.TextDisplay(f"## {text}"))
        self.divider()
        return self

    def subheader(self, text: str) -> Panel:
        self.container.add_item(ui.TextDisplay(f"### {text}"))
        return self

    def text(self, markdown: str) -> Panel:
        self.container.add_item(ui.TextDisplay(markdown))
        return self

    def field(self, name: str, value: str) -> Panel:
        self.container.add_item(ui.TextDisplay(f"**{name}**\n{value}"))
        return self

    def divider(self, *, large: bool = False) -> Panel:
        spacing = (
            discord.SeparatorSpacing.large if large else discord.SeparatorSpacing.small
        )
        self.container.add_item(ui.Separator(spacing=spacing))
        return self

    def footer(self, text: str) -> Panel:
        self.divider()
        self.container.add_item(ui.TextDisplay(f"-# {text}"))
        return self

    def section(self, *lines: str, thumbnail: str) -> Panel:
        """Text with an image accessory (e.g. a profile with an avatar)."""
        self.container.add_item(
            ui.Section(
                *[ui.TextDisplay(line) for line in lines],
                accessory=ui.Thumbnail(media=thumbnail),
            )
        )
        return self

    def buttons(self, *buttons: ui.Button) -> ui.ActionRow:
        row = ui.ActionRow()
        for button in buttons:
            row.add_item(button)
        self.container.add_item(row)
        return row

    def select(self, select: ui.Select) -> Panel:
        row = ui.ActionRow()
        row.add_item(select)
        self.container.add_item(row)
        return self

    # ── behaviour ───────────────────────────────────────────────────────

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """If an author is set, only they may press this panel's controls."""
        if self.author_id is None or interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "🛡️ These controls belong to another townsfolk.", ephemeral=True
        )
        return False

    async def on_timeout(self) -> None:
        for child in self.walk_children():
            if isinstance(child, (ui.Button, ui.Select)):
                child.disabled = True
        message = getattr(self, "message", None)
        if message is not None:
            try:
                await message.edit(view=self)
            except discord.HTTPException:
                pass


def simple_panel(body: str, *, accent: discord.Colour = Palette.GOLD) -> Panel:
    """A one-liner panel for short notices, with no interactive parts."""
    panel = Panel(accent=accent, timeout=None)
    panel.text(body)
    return panel
