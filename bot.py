"""Medieval town economy bot — entry point."""

import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from econ.database import Database

load_dotenv()

log = logging.getLogger("medieval-bot")

EXTENSIONS = ("cogs.jobs", "cogs.economy", "cogs.market")


class MedievalBot(commands.Bot):
    def __init__(self):
        # Slash commands only — no privileged intents needed.
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            help_command=None,
        )
        self.db = Database(os.getenv("DB_PATH", "economy.db"))

    async def setup_hook(self) -> None:
        await self.db.connect()
        for ext in EXTENSIONS:
            await self.load_extension(ext)

        guild_id = os.getenv("GUILD_ID")
        if guild_id:
            # Instant sync for one server (handy while testing).
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
                type=discord.ActivityType.watching, name="the town square | /job list"
            )
        )

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
