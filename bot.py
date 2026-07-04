"""Medieval town economy bot, entry point.

Commands are hybrid: every one works both as `.command` (prefix) and
`/command` (slash). Prefix commands require the Message Content intent,
enabled in the Discord Developer Portal under Bot → Privileged Gateway
Intents.
"""

import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from econ import captcha
from econ.database import Database
from ui.panels import Palette, captcha_panel, simple_panel

load_dotenv()

log = logging.getLogger("medieval-bot")

PREFIX = os.getenv("PREFIX", ".")
EXTENSIONS = (
    "cogs.jobs", "cogs.economy", "cogs.market", "cogs.venture", "cogs.crime",
    "cogs.brew", "cogs.minigames", "cogs.craft", "cogs.consumables", "cogs.town",
    "cogs.info",
)


class GuardedTree(app_commands.CommandTree):
    """Blocks slash commands while a town-guard check is unanswered."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
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
        return True


class MedievalBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # required for .prefix commands
        super().__init__(
            command_prefix=commands.when_mentioned_or(PREFIX),
            intents=intents,
            help_command=None,  # cogs/info.py provides .help
            case_insensitive=True,
            strip_after_prefix=True,
            tree_cls=GuardedTree,
            # Mentions render as highlights but never ping anyone.
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.db = Database(
            sqlite_path=os.getenv("DB_PATH", "economy.db"),
            postgres_url=os.getenv("DATABASE_URL"),
        )
        # name -> "</name:id>" clickable slash-command mention, filled in
        # after sync (see _build_command_mentions). cogs/info.py's .help
        # renders these so its command list is clickable, falling back to
        # plain ".name" text for anything not in here.
        self.command_mentions: dict[str, str] = {}

    async def setup_hook(self) -> None:
        await self.db.connect()
        for ext in EXTENSIONS:
            await self.load_extension(ext)

        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            # Instant sync to one server (handy while testing).
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to guild %s", len(synced), guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take up to an hour)", len(synced))

        self.command_mentions = self._build_command_mentions(synced)
        log.info("Cached %d slash-command mentions for .help", len(self.command_mentions))

    def _build_command_mentions(
        self, synced: list[app_commands.AppCommand]
    ) -> dict[str, str]:
        """Map each command name to its clickable ``</name:id>`` mention.

        A command mention is just text Discord's client turns into a
        chip; the id has to be the one Discord assigned at sync, which
        is exactly what ``tree.sync()`` hands back, so no extra fetch is
        needed. Groups (only ``job`` today) can't be mentioned bare, so
        their name resolves to the fallback subcommand's mention instead
        (``.job`` -> ``</job board:id>``), leaving ``.job`` clickable and
        landing on the same job board it opens as a prefix command."""
        mentions: dict[str, str] = {}
        for cmd in synced:
            subs = [
                o for o in cmd.options
                if isinstance(o, app_commands.AppCommandGroup)
            ]
            if not subs:
                mentions[cmd.name] = cmd.mention
                continue
            for sub in subs:
                mentions[f"{cmd.name} {sub.name}"] = sub.mention
            fallback = getattr(self.get_command(cmd.name), "fallback", None)
            if fallback and f"{cmd.name} {fallback}" in mentions:
                mentions[cmd.name] = mentions[f"{cmd.name} {fallback}"]
        return mentions

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild and captcha.has_pending(message.guild.id, message.author.id):
            if captcha.try_solve(message.guild.id, message.author.id, message.content):
                await message.channel.send(
                    view=simple_panel(
                        f"✅ The guard nods and waves {message.author.mention} "
                        "through the gates. Carry on!",
                        accent=Palette.GREEN,
                    )
                )
            elif message.content.startswith(PREFIX):
                # Commands stay locked; repeat the challenge.
                await message.channel.send(
                    view=captcha_panel(
                        captcha.pending_code(message.guild.id, message.author.id)
                    )
                )
            return
        await self.process_commands(message)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"the town square | {PREFIX}help",
            )
        )

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.NoPrivateMessage):
            message = "🏰 The town only does business inside a server."
        elif isinstance(error, commands.MissingRequiredArgument):
            message = (
                f"📜 Missing `{error.param.name}`, "
                f"try `{PREFIX}help` for how each command is used."
            )
        elif isinstance(error, (commands.BadArgument, commands.RangeError)):
            message = "📜 The town clerk cannot make sense of that value."
        elif isinstance(error, commands.MemberNotFound):
            message = "🔍 No townsfolk by that name lives here."
        elif isinstance(error, commands.MissingPermissions):
            message = "🛡️ Only town hall administrators may do that."
        else:
            log.exception("Unhandled command error in %s", ctx.command, exc_info=error)
            message = "⚠️ Something went awry in the town hall. The scribes have been notified."
        try:
            await ctx.send(view=simple_panel(message, accent=Palette.RED), ephemeral=True)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        await self.db.close()
        await super().close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit(
            "DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token."
        )
    MedievalBot().run(token)


if __name__ == "__main__":
    main()
