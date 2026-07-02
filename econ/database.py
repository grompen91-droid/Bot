"""Storage layer with versioned migrations.

Two backends behind one API:
- PostgreSQL when DATABASE_URL is set (Railway, or any hosted Postgres).
  Data persists across deploys with no volumes needed.
- SQLite otherwise (local development, small self-hosting).

All queries are written once in a shared dialect (?-placeholders,
BIGINT ids, ON CONFLICT upserts) and adapted per driver. To evolve the
schema, append a new SQL script to MIGRATIONS; it runs exactly once per
database, tracked in the schema_meta table.
"""

import os

MIGRATIONS: list[str] = [
    # v1, initial schema
    """
    CREATE TABLE IF NOT EXISTS users (
        guild_id     BIGINT NOT NULL,
        user_id      BIGINT NOT NULL,
        gold         BIGINT NOT NULL DEFAULT 0,
        job          TEXT,
        last_daily   TEXT,
        daily_streak BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    );
    CREATE TABLE IF NOT EXISTS skills (
        guild_id  BIGINT NOT NULL,
        user_id   BIGINT NOT NULL,
        job       TEXT   NOT NULL,
        level     BIGINT NOT NULL DEFAULT 1,
        xp        BIGINT NOT NULL DEFAULT 0,
        last_work DOUBLE PRECISION NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, job)
    );
    CREATE TABLE IF NOT EXISTS inventory (
        guild_id BIGINT NOT NULL,
        user_id  BIGINT NOT NULL,
        item     TEXT   NOT NULL,
        qty      BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, item)
    );
    CREATE TABLE IF NOT EXISTS tools (
        guild_id BIGINT NOT NULL,
        user_id  BIGINT NOT NULL,
        job      TEXT   NOT NULL,
        tier     BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, job)
    );
    CREATE TABLE IF NOT EXISTS stats (
        guild_id BIGINT NOT NULL,
        user_id  BIGINT NOT NULL,
        key      TEXT   NOT NULL,
        value    BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, key)
    );
    """,
    # v2, cooldown between job switches
    """
    ALTER TABLE users ADD COLUMN last_job_switch DOUBLE PRECISION NOT NULL DEFAULT 0;
    """,
    # v3, the venture minigame
    """
    ALTER TABLE users ADD COLUMN last_venture DOUBLE PRECISION NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN venture_streak BIGINT NOT NULL DEFAULT 0;
    """,
]


class Database:
    def __init__(self, sqlite_path: str = "economy.db", postgres_url: str | None = None):
        self.sqlite_path = sqlite_path
        self.postgres_url = postgres_url
        self.is_postgres = bool(postgres_url)
        self._pool = None  # asyncpg pool
        self._conn = None  # aiosqlite connection

    # ── driver plumbing ─────────────────────────────────────────────────

    def _q(self, sql: str) -> str:
        """Convert ?-placeholders to $1..$n for asyncpg."""
        if not self.is_postgres:
            return sql
        parts = sql.split("?")
        out = parts[0]
        for i, part in enumerate(parts[1:], start=1):
            out += f"${i}{part}"
        return out

    async def connect(self) -> None:
        if self.is_postgres:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self.postgres_url, min_size=1, max_size=5
            )
        else:
            import aiosqlite

            parent = os.path.dirname(os.path.abspath(self.sqlite_path))
            os.makedirs(parent, exist_ok=True)
            self._conn = await aiosqlite.connect(self.sqlite_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode = WAL")
            await self._conn.commit()
        await self._migrate()

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _script(self, sql: str) -> None:
        """Run a multi-statement script (no parameters)."""
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                await conn.execute(sql)
        else:
            await self._conn.executescript(sql)
            await self._conn.commit()

    async def execute(self, sql: str, *args) -> None:
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                await conn.execute(self._q(sql), *args)
        else:
            await self._conn.execute(sql, args)
            await self._conn.commit()

    async def fetchone(self, sql: str, *args):
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                return await conn.fetchrow(self._q(sql), *args)
        cur = await self._conn.execute(sql, args)
        return await cur.fetchone()

    async def fetchall(self, sql: str, *args) -> list:
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                return await conn.fetch(self._q(sql), *args)
        cur = await self._conn.execute(sql, args)
        return await cur.fetchall()

    async def _migrate(self) -> None:
        await self._script(
            "CREATE TABLE IF NOT EXISTS schema_meta (version BIGINT NOT NULL)"
        )
        row = await self.fetchone("SELECT version FROM schema_meta")
        if row is None:
            version = 0
            await self.execute("INSERT INTO schema_meta (version) VALUES (?)", 0)
        else:
            version = row["version"]
        for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
            await self._script(script)
            await self.execute("UPDATE schema_meta SET version = ?", target)

    # ── users ───────────────────────────────────────────────────────────

    async def get_user(self, guild_id: int, user_id: int):
        await self.execute(
            "INSERT INTO users (guild_id, user_id) VALUES (?, ?) "
            "ON CONFLICT (guild_id, user_id) DO NOTHING",
            guild_id, user_id,
        )
        return await self.fetchone(
            "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )

    async def add_gold(self, guild_id: int, user_id: int, amount: int) -> int:
        """Add (or subtract) gold; returns the new balance."""
        await self.get_user(guild_id, user_id)
        await self.execute(
            "UPDATE users SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
            amount, guild_id, user_id,
        )
        row = await self.fetchone(
            "SELECT gold FROM users WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        return row["gold"]

    async def transfer_gold(
        self, guild_id: int, from_id: int, to_id: int, amount: int
    ) -> bool:
        """Move gold between users; False if the sender is short."""
        sender = await self.get_user(guild_id, from_id)
        if sender["gold"] < amount:
            return False
        await self.get_user(guild_id, to_id)
        await self.execute(
            "UPDATE users SET gold = gold - ? WHERE guild_id = ? AND user_id = ?",
            amount, guild_id, from_id,
        )
        await self.execute(
            "UPDATE users SET gold = gold + ? WHERE guild_id = ? AND user_id = ?",
            amount, guild_id, to_id,
        )
        return True

    async def set_job(
        self, guild_id: int, user_id: int, job: str | None, switched_at: float
    ) -> None:
        await self.get_user(guild_id, user_id)
        await self.execute(
            "UPDATE users SET job = ?, last_job_switch = ? "
            "WHERE guild_id = ? AND user_id = ?",
            job, switched_at, guild_id, user_id,
        )

    async def set_daily(
        self, guild_id: int, user_id: int, date_iso: str, streak: int
    ) -> None:
        await self.execute(
            "UPDATE users SET last_daily = ?, daily_streak = ? "
            "WHERE guild_id = ? AND user_id = ?",
            date_iso, streak, guild_id, user_id,
        )

    async def set_venture(
        self, guild_id: int, user_id: int, when: float, streak: int
    ) -> None:
        await self.execute(
            "UPDATE users SET last_venture = ?, venture_streak = ? "
            "WHERE guild_id = ? AND user_id = ?",
            when, streak, guild_id, user_id,
        )

    # ── skills ──────────────────────────────────────────────────────────

    async def get_skill(self, guild_id: int, user_id: int, job: str):
        await self.execute(
            "INSERT INTO skills (guild_id, user_id, job) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id, job) DO NOTHING",
            guild_id, user_id, job,
        )
        return await self.fetchone(
            "SELECT * FROM skills WHERE guild_id = ? AND user_id = ? AND job = ?",
            guild_id, user_id, job,
        )

    async def update_skill(
        self, guild_id: int, user_id: int, job: str,
        level: int, xp: int, last_work: float,
    ) -> None:
        await self.execute(
            "UPDATE skills SET level = ?, xp = ?, last_work = ? "
            "WHERE guild_id = ? AND user_id = ? AND job = ?",
            level, xp, last_work, guild_id, user_id, job,
        )

    async def peek_skill(self, guild_id: int, user_id: int, job: str) -> dict:
        """Read-only skill lookup that never creates a row. Used for
        previews (e.g. `.job info`) so merely inspecting a trade can't
        inflate total_level() with a phantom level-1 entry."""
        row = await self.fetchone(
            "SELECT level, xp, last_work FROM skills "
            "WHERE guild_id = ? AND user_id = ? AND job = ?",
            guild_id, user_id, job,
        )
        return dict(row) if row is not None else {"level": 1, "xp": 0, "last_work": 0}

    async def get_all_skills(self, guild_id: int, user_id: int) -> list:
        return await self.fetchall(
            "SELECT * FROM skills WHERE guild_id = ? AND user_id = ? "
            "ORDER BY level DESC, xp DESC",
            guild_id, user_id,
        )

    async def total_level(self, guild_id: int, user_id: int) -> int:
        row = await self.fetchone(
            "SELECT COALESCE(SUM(level), 0) AS total FROM skills "
            "WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        return row["total"]

    # ── inventory ───────────────────────────────────────────────────────

    async def add_item(self, guild_id: int, user_id: int, item: str, qty: int) -> None:
        await self.execute(
            "INSERT INTO inventory (guild_id, user_id, item, qty) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (guild_id, user_id, item) "
            "DO UPDATE SET qty = inventory.qty + excluded.qty",
            guild_id, user_id, item, qty,
        )

    async def get_inventory(self, guild_id: int, user_id: int) -> list:
        return await self.fetchall(
            "SELECT item, qty FROM inventory "
            "WHERE guild_id = ? AND user_id = ? AND qty > 0 ORDER BY item",
            guild_id, user_id,
        )

    async def get_item_qty(self, guild_id: int, user_id: int, item: str) -> int:
        row = await self.fetchone(
            "SELECT qty FROM inventory WHERE guild_id = ? AND user_id = ? AND item = ?",
            guild_id, user_id, item,
        )
        return row["qty"] if row else 0

    async def remove_item(
        self, guild_id: int, user_id: int, item: str, qty: int
    ) -> bool:
        """Remove qty of an item; False if the user doesn't hold enough."""
        if await self.get_item_qty(guild_id, user_id, item) < qty:
            return False
        await self.execute(
            "UPDATE inventory SET qty = qty - ? "
            "WHERE guild_id = ? AND user_id = ? AND item = ?",
            qty, guild_id, user_id, item,
        )
        await self.execute(
            "DELETE FROM inventory "
            "WHERE guild_id = ? AND user_id = ? AND item = ? AND qty <= 0",
            guild_id, user_id, item,
        )
        return True

    # ── tools ───────────────────────────────────────────────────────────

    async def get_tool_tier(self, guild_id: int, user_id: int, job: str) -> int:
        row = await self.fetchone(
            "SELECT tier FROM tools WHERE guild_id = ? AND user_id = ? AND job = ?",
            guild_id, user_id, job,
        )
        return row["tier"] if row else 0

    async def set_tool_tier(
        self, guild_id: int, user_id: int, job: str, tier: int
    ) -> None:
        await self.execute(
            "INSERT INTO tools (guild_id, user_id, job, tier) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (guild_id, user_id, job) DO UPDATE SET tier = excluded.tier",
            guild_id, user_id, job, tier,
        )

    # ── stats (lifetime counters: achievements, richer profiles, …) ─────

    async def incr_stat(
        self, guild_id: int, user_id: int, key: str, amount: int = 1
    ) -> None:
        await self.execute(
            "INSERT INTO stats (guild_id, user_id, key, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (guild_id, user_id, key) "
            "DO UPDATE SET value = stats.value + excluded.value",
            guild_id, user_id, key, amount,
        )

    async def get_stats(self, guild_id: int, user_id: int) -> dict[str, int]:
        rows = await self.fetchall(
            "SELECT key, value FROM stats WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        return {row["key"]: row["value"] for row in rows}

    # ── leaderboards ────────────────────────────────────────────────────

    async def top_gold(self, guild_id: int, limit: int = 10) -> list:
        return await self.fetchall(
            "SELECT user_id, gold FROM users WHERE guild_id = ? AND gold > 0 "
            "ORDER BY gold DESC LIMIT ?",
            guild_id, limit,
        )

    async def top_skills(self, guild_id: int, limit: int = 10) -> list:
        return await self.fetchall(
            "SELECT user_id, SUM(level) AS total_level, MAX(level) AS best_level "
            "FROM skills WHERE guild_id = ? GROUP BY user_id "
            "ORDER BY total_level DESC LIMIT ?",
            guild_id, limit,
        )
