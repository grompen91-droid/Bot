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

from econ import captcha


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
        small = "\n".join(f"-# {line}" for line in text.split("\n"))
        self.container.add_item(ui.TextDisplay(small))
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
        """Guard checks come first; then, if an author is set, only they
        may press this panel's controls."""
        if interaction.guild_id and captcha.has_pending(
            interaction.guild_id, interaction.user.id
        ):
            await interaction.response.send_message(
                view=captcha_panel(
                    captcha.pending_code(interaction.guild_id, interaction.user.id)
                ),
                ephemeral=True,
            )
            return False
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


class RoundPanel(Panel):
    """A Panel whose expiry resolves the owner as a timeout failure,
    instead of the base Panel's disable-in-place. Used by any timed,
    multi-step flow (the per-job minigames, the cauldron brew) where a
    round that's replaced by a new one must have its own background
    timeout task explicitly stopped, or a stale timer from an earlier
    round can fire later and wrongly kill an attempt still in
    progress (discord.py refreshes a view's own timeout on every tap,
    but a NEW view sent via edit_message doesn't cancel the old one).

        class MySession:
            def __init__(self):
                self.current_panel = None

            def round_panel(self):
                panel = RoundPanel(self, timeout=10)
                ...
                self.current_panel = panel
                return panel

            async def on_tap(self, interaction, ...):
                if self.current_panel is not None:
                    self.current_panel.stop()
                ...  # build and send the next panel, or resolve

            async def on_round_timeout(self, message):
                ...  # resolve as a failure and message.edit(view=...)

    `owner` needs an `on_round_timeout(message)` coroutine.
    """

    def __init__(self, owner, **kwargs):
        super().__init__(**kwargs)
        self.owner = owner

    async def on_timeout(self) -> None:
        message = getattr(self, "message", None)
        if message is not None:
            await self.owner.on_round_timeout(message)


def simple_panel(body: str, *, accent: discord.Colour = Palette.GOLD) -> Panel:
    """A one-liner panel for short notices, with no interactive parts."""
    panel = Panel(accent=accent, timeout=None)
    panel.text(body)
    return panel


# ── ledger chips ─────────────────────────────────────────────────────────
# Discord's normal font is proportional, so amounts can never line up in
# plain text. These render as inline-code (monospace) chips with fixed
# column widths, giving every list a clean aligned coin column.
# Column = (text, width); positive width = left-aligned, negative = right.

NAME_W = 16   # item/tool names (all data names are kept to 16 chars max)
QTY_W = 4     # "x999"
AMT_W = 6     # "30,000"
WEALTH_W = 10  # "999,999,999" — leaderboard totals, bank balances


def chip(*cols: tuple[str, int]) -> str:
    parts = []
    for text, width in cols:
        w = abs(width)
        if len(text) > w:
            text = text[: w - 1] + "…"
        parts.append(f"{text:>{w}}" if width < 0 else f"{text:<{w}}")
    return "`" + " ".join(parts) + "`"


class InteractionSender:
    """Adapts a component interaction to the ctx.send(view=...) shape a
    Panel-driven flow expects, for any "confirm/pick a button -> that
    same message becomes the next screen" sequence (the difficulty
    picker and .rob's confirm step, the cauldron brew's own picker).

    An interaction's response slot can only be used once. The first
    .send() edits the message the button lived on, exactly like the
    old single-shot flows; anything after that (e.g. a *test command's
    "TEST MODE" notice followed by the actual first round) goes out as
    a followup instead, a genuinely new message, matching what calling
    ctx.send() twice would have produced."""

    def __init__(self, interaction: discord.Interaction):
        self.interaction = interaction
        self._responded = False

    async def send(self, view=None, **kwargs) -> discord.Message:
        if not self._responded:
            self._responded = True
            await self.interaction.response.edit_message(view=view)
            return self.interaction.message
        return await self.interaction.followup.send(view=view, **kwargs)


def captcha_panel(code: str) -> Panel:
    """The town guard's letter challenge."""
    panel = Panel(accent=Palette.RED, timeout=None)
    panel.is_captcha = True
    panel.header("🛡️ Town Guard Checkpoint")
    panel.text(
        "Golems and automatons are not welcome in town! Prove you are "
        "flesh and blood: **type these letters in chat** to carry on."
    )
    panel.text(f"# `{' '.join(code)}`")
    panel.footer("just send the letters as a message · case doesn't matter")
    return panel
