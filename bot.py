"""Medieval town economy bot — entry point.

Commands are hybrid: every one works both as `.command` (prefix) and
`/command` (slash). Prefix commands require the Message Content intent,
enabled in the Discord Developer Portal under Bot → Privileged Gateway
Intents.
"""

import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from econ.database import Database
from ui.panels import Palette, simple_panel

load_dotenv()

log = logging.getLogger("medieval-bot")

PREFIX = os.getenv("PREFIX", ".")
EXTENSIONS = ("cogs.jobs", "cogs.economy", "cogs.market", "cogs.info")


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
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )
        self.db = Database(os.getenv("DB_PATH", "economy.db"))

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
                f"📜 Missing `{error.param.name}` — "
                f"try `{PREFIX}help` for how each command is used."
            )
        elif isinstance(error, (commands.BadArgument, commands.RangeError)):
            message = "📜 The town clerk cannot make sense of that value."
        elif isinstance(error, commands.MemberNotFound):
            message = "🔍 No townsfolk by that name lives here."
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
