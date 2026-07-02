"""SQLite persistence layer (per-guild economy)."""

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    gold         INTEGER NOT NULL DEFAULT 0,
    job          TEXT,
    last_daily   TEXT,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS skills (
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    job       TEXT    NOT NULL,
    level     INTEGER NOT NULL DEFAULT 1,
    xp        INTEGER NOT NULL DEFAULT 0,
    last_work REAL    NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, job)
);

CREATE TABLE IF NOT EXISTS inventory (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    item     TEXT    NOT NULL,
    qty      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, item)
);

CREATE TABLE IF NOT EXISTS tools (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    job      TEXT    NOT NULL,
    tier     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, job)
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    # -- users -------------------------------------------------------------

    async def get_user(self, guild_id: int, user_id: int) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT OR IGNORE INTO users (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return await cur.fetchone()

    async def add_gold(self, guild_id: int, user_id: int, amount: int) -> int:
        """Add (or subtract) gold and return the new balance."""
        await self.get_user(guild_id, user_id)
        await self.conn.execute(
            "UPDATE users SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            "SELECT gold FROM users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return (await cur.fetchone())["gold"]

    async def transfer_gold(
        self, guild_id: int, from_id: int, to_id: int, amount: int
    ) -> bool:
        """Move gold between users atomically. Returns False if sender is short."""
        sender = await self.get_user(guild_id, from_id)
        if sender["gold"] < amount:
            return False
        await self.get_user(guild_id, to_id)
        await self.conn.execute(
            "UPDATE users SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, from_id),
        )
        await self.conn.execute(
            "UPDATE users SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, to_id),
        )
        await self.conn.commit()
        return True

    async def set_job(self, guild_id: int, user_id: int, job: str | None) -> None:
        await self.get_user(guild_id, user_id)
        await self.conn.execute(
            "UPDATE users SET job = ? WHERE guild_id = ? AND user_id = ?",
            (job, guild_id, user_id),
        )
        await self.conn.commit()

    async def set_daily(
        self, guild_id: int, user_id: int, date_iso: str, streak: int
    ) -> None:
        await self.conn.execute(
            "UPDATE users SET last_daily = ?, daily_streak = ? "
            "WHERE guild_id = ? AND user_id = ?",
            (date_iso, streak, guild_id, user_id),
        )
        await self.conn.commit()

    # -- skills ------------------------------------------------------------

    async def get_skill(self, guild_id: int, user_id: int, job: str) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT OR IGNORE INTO skills (guild_id, user_id, job) VALUES (?, ?, ?)",
            (guild_id, user_id, job),
        )
        await self.conn.commit()
        cur = await self.conn.execute(
            "SELECT * FROM skills WHERE guild_id = ? AND user_id = ? AND job = ?",
            (guild_id, user_id, job),
        )
        return await cur.fetchone()

    async def update_skill(
        self, guild_id: int, user_id: int, job: str,
        level: int, xp: int, last_work: float,
    ) -> None:
        await self.conn.execute(
            "UPDATE skills SET level = ?, xp = ?, last_work = ? "
            "WHERE guild_id = ? AND user_id = ? AND job = ?",
            (level, xp, last_work, guild_id, user_id, job),
        )
        await self.conn.commit()

    async def get_all_skills(self, guild_id: int, user_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM skills WHERE guild_id = ? AND user_id = ? "
            "ORDER BY level DESC, xp DESC",
            (guild_id, user_id),
        )
        return await cur.fetchall()

    # -- inventory ---------------------------------------------------------

    async def add_item(self, guild_id: int, user_id: int, item: str, qty: int) -> None:
        await self.conn.execute(
            "INSERT INTO inventory (guild_id, user_id, item, qty) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, item) DO UPDATE SET qty = qty + ?",
            (guild_id, user_id, item, qty, qty),
        )
        await self.conn.commit()

    async def get_inventory(self, guild_id: int, user_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT item, qty FROM inventory "
            "WHERE guild_id = ? AND user_id = ? AND qty > 0 ORDER BY item",
            (guild_id, user_id),
        )
        return await cur.fetchall()

    async def get_item_qty(self, guild_id: int, user_id: int, item: str) -> int:
        cur = await self.conn.execute(
            "SELECT qty FROM inventory WHERE guild_id = ? AND user_id = ? AND item = ?",
            (guild_id, user_id, item),
        )
        row = await cur.fetchone()
        return row["qty"] if row else 0

    async def remove_item(
        self, guild_id: int, user_id: int, item: str, qty: int
    ) -> bool:
        """Remove qty of item. Returns False if the user doesn't have enough."""
        if await self.get_item_qty(guild_id, user_id, item) < qty:
            return False
        await self.conn.execute(
            "UPDATE inventory SET qty = qty - ? "
            "WHERE guild_id = ? AND user_id = ? AND item = ?",
            (qty, guild_id, user_id, item),
        )
        await self.conn.execute(
            "DELETE FROM inventory "
            "WHERE guild_id = ? AND user_id = ? AND item = ? AND qty <= 0",
            (guild_id, user_id, item),
        )
        await self.conn.commit()
        return True

    # -- tools ---------------------------------------------------------------

    async def get_tool_tier(self, guild_id: int, user_id: int, job: str) -> int:
        cur = await self.conn.execute(
            "SELECT tier FROM tools WHERE guild_id = ? AND user_id = ? AND job = ?",
            (guild_id, user_id, job),
        )
        row = await cur.fetchone()
        return row["tier"] if row else 0

    async def set_tool_tier(
        self, guild_id: int, user_id: int, job: str, tier: int
    ) -> None:
        await self.conn.execute(
            "INSERT INTO tools (guild_id, user_id, job, tier) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(guild_id, user_id, job) DO UPDATE SET tier = ?",
            (guild_id, user_id, job, tier, tier),
        )
        await self.conn.commit()

    # -- leaderboards --------------------------------------------------------

    async def top_gold(self, guild_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT user_id, gold FROM users WHERE guild_id = ? AND gold > 0 "
            "ORDER BY gold DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()

    async def top_skills(self, guild_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT user_id, SUM(level) AS total_level FROM skills "
            "WHERE guild_id = ? GROUP BY user_id "
            "ORDER BY total_level DESC LIMIT ?",
            (guild_id, limit),
        )
        return await cur.fetchall()
