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
from functools import lru_cache

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
    # v4, the bank and pickpocketing
    """
    ALTER TABLE users ADD COLUMN bank_gold BIGINT NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN bank_tier BIGINT NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN last_pickpocket DOUBLE PRECISION NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN robbed_until DOUBLE PRECISION NOT NULL DEFAULT 0;
    """,
    # v5, the cauldron brew
    """
    ALTER TABLE users ADD COLUMN last_brew DOUBLE PRECISION NOT NULL DEFAULT 0;
    """,
    # v6, the other 7 per-job minigames (one shared cooldown table rather
    # than a users column per trade)
    """
    CREATE TABLE IF NOT EXISTS minigame_cooldowns (
        guild_id    BIGINT NOT NULL,
        user_id     BIGINT NOT NULL,
        job         TEXT   NOT NULL,
        last_played DOUBLE PRECISION NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, job)
    );
    """,
    # v7, infamy and fame: the Criminal trade's reputation, and the
    # legit minigames' reputation, two long-game tracks (superseded by
    # v8's single signed reputation counter, kept here for history)
    """
    ALTER TABLE users ADD COLUMN infamy BIGINT NOT NULL DEFAULT 0;
    ALTER TABLE users ADD COLUMN fame BIGINT NOT NULL DEFAULT 0;
    """,
    # v8, collapse infamy and fame into one signed reputation counter:
    # crime pulls it down, honest minigame success pulls it up
    """
    ALTER TABLE users ADD COLUMN reputation BIGINT NOT NULL DEFAULT 0;
    UPDATE users SET reputation = fame - infamy;
    ALTER TABLE users DROP COLUMN infamy;
    ALTER TABLE users DROP COLUMN fame;
    """,
    # v9, consumables: temporary buffs from potions/foods, .use'd from
    # the satchel. Keyed by item (not a made-up buff id) so using the
    # same item again just refreshes its own duration.
    """
    CREATE TABLE IF NOT EXISTS active_buffs (
        guild_id   BIGINT NOT NULL,
        user_id    BIGINT NOT NULL,
        item       TEXT   NOT NULL,
        expires_at DOUBLE PRECISION NOT NULL,
        PRIMARY KEY (guild_id, user_id, item)
    );
    """,
    # v10, .shop's per-item daily purchase limit. `day` is a UTC
    # ordinal day (formulas.utc_day()), not a timestamp, so "today's"
    # row is a plain equality lookup; old days' rows are simply never
    # matched again, same "leave it, don't sweep it" approach as
    # active_buffs above.
    """
    CREATE TABLE IF NOT EXISTS store_purchases (
        guild_id BIGINT NOT NULL,
        user_id  BIGINT NOT NULL,
        item     TEXT   NOT NULL,
        day      BIGINT NOT NULL,
        qty      BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, item, day)
    );
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

    @staticmethod
    @lru_cache(maxsize=512)
    def _to_postgres(sql: str) -> str:
        """Convert ?-placeholders to $1..$n for asyncpg. The query set is
        small and fixed, so the conversion is memoised."""
        parts = sql.split("?")
        out = parts[0]
        for i, part in enumerate(parts[1:], start=1):
            out += f"${i}{part}"
        return out

    def _q(self, sql: str) -> str:
        return self._to_postgres(sql) if self.is_postgres else sql

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

    async def execute_rowcount(self, sql: str, *args) -> int:
        """Execute and return how many rows were affected. This is what
        makes conditional updates (`... AND gold >= ?`) usable as atomic
        check-and-take operations instead of racy check-then-act pairs."""
        if self.is_postgres:
            async with self._pool.acquire() as conn:
                status = await conn.execute(self._q(sql), *args)
            try:
                return int(status.rsplit(" ", 1)[-1])  # e.g. "UPDATE 1"
            except ValueError:
                return 0
        cur = await self._conn.execute(sql, args)
        await self._conn.commit()
        return cur.rowcount

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
            await self._apply_migration(script, target)

    async def _apply_migration(self, script: str, target_version: int) -> None:
        """Run a migration script and bump schema_meta atomically, so an
        interrupted deploy can never leave the schema and the recorded
        version out of sync. If it turns out the schema already has this
        migration's changes (an earlier attempt applied them before
        crashing, right before the version bump), just catch the
        version up instead of failing on 'column already exists' forever.
        """
        try:
            if self.is_postgres:
                async with self._pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.execute(script)
                        await conn.execute(
                            self._q("UPDATE schema_meta SET version = ?"),
                            target_version,
                        )
            else:
                await self._conn.executescript(script)
                await self._conn.execute(
                    "UPDATE schema_meta SET version = ?", (target_version,)
                )
                await self._conn.commit()
        except Exception as e:
            msg = str(e).lower()
            if "already exists" not in msg and "duplicate column" not in msg:
                raise
            await self.execute("UPDATE schema_meta SET version = ?", target_version)

    # ── users ───────────────────────────────────────────────────────────

    async def get_user(self, guild_id: int, user_id: int):
        # Fast path: almost every call is for a user who already exists,
        # so try the plain SELECT before paying for the ensure-INSERT.
        row = await self.fetchone(
            "SELECT * FROM users WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        if row is not None:
            return row
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
        await self.execute(
            "INSERT INTO users (guild_id, user_id, gold) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) "
            "DO UPDATE SET gold = users.gold + excluded.gold",
            guild_id, user_id, amount,
        )
        row = await self.fetchone(
            "SELECT gold FROM users WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        return row["gold"]

    async def spend_gold(self, guild_id: int, user_id: int, amount: int) -> bool:
        """Deduct gold only if the pocket covers it; False otherwise.
        The purchase primitive: a double-clicked buy button can't drive
        a purse negative through two racing deductions."""
        taken = await self.execute_rowcount(
            "UPDATE users SET gold = gold - ? "
            "WHERE guild_id = ? AND user_id = ? AND gold >= ?",
            amount, guild_id, user_id, amount,
        )
        return bool(taken)

    async def transfer_gold(
        self, guild_id: int, from_id: int, to_id: int, amount: int
    ) -> bool:
        """Move gold between users; False if the sender is short. The
        debit is a conditional update, so two concurrent transfers can
        never spend the same gold twice."""
        await self.get_user(guild_id, to_id)
        taken = await self.execute_rowcount(
            "UPDATE users SET gold = gold - ? "
            "WHERE guild_id = ? AND user_id = ? AND gold >= ?",
            amount, guild_id, from_id, amount,
        )
        if not taken:
            return False
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

    # ── bank ────────────────────────────────────────────────────────────

    async def deposit_gold(
        self, guild_id: int, user_id: int, amount: int, capacity: int
    ) -> bool:
        """Move pocket gold into the bank; False if the pocket is short
        or the bank would overflow. Conditional, so double-clicking the
        command can't overdraw the pocket or overfill the bank."""
        moved = await self.execute_rowcount(
            "UPDATE users SET gold = gold - ?, bank_gold = bank_gold + ? "
            "WHERE guild_id = ? AND user_id = ? "
            "AND gold >= ? AND bank_gold + ? <= ?",
            amount, amount, guild_id, user_id, amount, amount, capacity,
        )
        return bool(moved)

    async def withdraw_gold(self, guild_id: int, user_id: int, amount: int) -> bool:
        """Move banked gold back to the pocket; False if the bank is short."""
        moved = await self.execute_rowcount(
            "UPDATE users SET gold = gold + ?, bank_gold = bank_gold - ? "
            "WHERE guild_id = ? AND user_id = ? AND bank_gold >= ?",
            amount, amount, guild_id, user_id, amount,
        )
        return bool(moved)

    async def set_bank_tier(self, guild_id: int, user_id: int, tier: int) -> None:
        await self.execute(
            "UPDATE users SET bank_tier = ? WHERE guild_id = ? AND user_id = ?",
            tier, guild_id, user_id,
        )

    # ── pickpocketing ───────────────────────────────────────────────────

    async def set_last_pickpocket(self, guild_id: int, user_id: int, when: float) -> None:
        await self.execute(
            "UPDATE users SET last_pickpocket = ? WHERE guild_id = ? AND user_id = ?",
            when, guild_id, user_id,
        )

    async def set_robbed_until(self, guild_id: int, user_id: int, until: float) -> None:
        await self.execute(
            "UPDATE users SET robbed_until = ? WHERE guild_id = ? AND user_id = ?",
            until, guild_id, user_id,
        )

    # ── the cauldron brew ───────────────────────────────────────────────

    async def set_last_brew(self, guild_id: int, user_id: int, when: float) -> None:
        await self.execute(
            "UPDATE users SET last_brew = ? WHERE guild_id = ? AND user_id = ?",
            when, guild_id, user_id,
        )

    # ── reputation (infamy pulls it down, fame pulls it up) ─────────────

    async def add_reputation(self, guild_id: int, user_id: int, delta: int) -> int:
        """One signed counter for the whole reputation system: crime
        (Criminal .work/.pickpocket/.rob) passes a negative delta,
        succeeding at a legit minigame passes a positive one. The one
        way it snaps back is set_reputation(0) when a bank job goes
        wrong. Returns the new total."""
        await self.execute(
            "INSERT INTO users (guild_id, user_id, reputation) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) "
            "DO UPDATE SET reputation = users.reputation + excluded.reputation",
            guild_id, user_id, delta,
        )
        row = await self.fetchone(
            "SELECT reputation FROM users WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        return row["reputation"]

    async def set_reputation(self, guild_id: int, user_id: int, value: int) -> None:
        await self.execute(
            "UPDATE users SET reputation = ? WHERE guild_id = ? AND user_id = ?",
            value, guild_id, user_id,
        )

    # ── consumables & active buffs ───────────────────────────────────────

    async def add_buff(
        self, guild_id: int, user_id: int, item: str, expires_at: float
    ) -> None:
        """Using an item already active refreshes its expiry rather
        than stacking a second copy of the same buff."""
        await self.execute(
            "INSERT INTO active_buffs (guild_id, user_id, item, expires_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (guild_id, user_id, item) "
            "DO UPDATE SET expires_at = excluded.expires_at",
            guild_id, user_id, item, expires_at,
        )

    async def get_active_buffs(self, guild_id: int, user_id: int, now: float) -> list:
        """Already-expired rows are simply excluded, not deleted here --
        cheap and correct without a background sweep job."""
        return await self.fetchall(
            "SELECT item, expires_at FROM active_buffs "
            "WHERE guild_id = ? AND user_id = ? AND expires_at > ?",
            guild_id, user_id, now,
        )

    # ── .shop's daily purchase limit ────────────────────────────────────

    async def get_store_purchases_today(
        self, guild_id: int, user_id: int, day: int
    ) -> dict[str, int]:
        """Everything bought from .shop today, one query instead of one
        per item when rendering the buy list."""
        rows = await self.fetchall(
            "SELECT item, qty FROM store_purchases "
            "WHERE guild_id = ? AND user_id = ? AND day = ?",
            guild_id, user_id, day,
        )
        return {row["item"]: row["qty"] for row in rows}

    async def try_reserve_store_purchase(
        self, guild_id: int, user_id: int, item: str, day: int, qty: int, limit: int
    ) -> bool:
        """Atomically records `qty` more of `item` bought today, but only
        if that wouldn't push the day's total over `limit`; returns
        False (and changes nothing) otherwise. Conditional update, same
        pattern as spend_gold/remove_item, so two rapid clicks on the
        same item can't both slip under the cap. Call release_store_
        purchase to undo the reservation if the purchase then fails for
        some other reason (e.g. not enough gold)."""
        await self.execute(
            "INSERT INTO store_purchases (guild_id, user_id, item, day, qty) "
            "VALUES (?, ?, ?, ?, 0) ON CONFLICT (guild_id, user_id, item, day) "
            "DO NOTHING",
            guild_id, user_id, item, day,
        )
        reserved = await self.execute_rowcount(
            "UPDATE store_purchases SET qty = qty + ? "
            "WHERE guild_id = ? AND user_id = ? AND item = ? AND day = ? "
            "AND qty + ? <= ?",
            qty, guild_id, user_id, item, day, qty, limit,
        )
        return bool(reserved)

    async def release_store_purchase(
        self, guild_id: int, user_id: int, item: str, day: int, qty: int
    ) -> None:
        await self.execute(
            "UPDATE store_purchases SET qty = qty - ? "
            "WHERE guild_id = ? AND user_id = ? AND item = ? AND day = ?",
            qty, guild_id, user_id, item, day,
        )

    # ── the other per-job minigames ─────────────────────────────────────

    async def get_minigame_cooldown(self, guild_id: int, user_id: int, job: str) -> float:
        row = await self.fetchone(
            "SELECT last_played FROM minigame_cooldowns "
            "WHERE guild_id = ? AND user_id = ? AND job = ?",
            guild_id, user_id, job,
        )
        return row["last_played"] if row else 0.0

    async def get_minigame_cooldowns(
        self, guild_id: int, user_id: int
    ) -> dict[str, float]:
        """All of a player's minigame cooldowns in one query, for views
        like .cd that would otherwise fetch them one game at a time."""
        rows = await self.fetchall(
            "SELECT job, last_played FROM minigame_cooldowns "
            "WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        return {row["job"]: row["last_played"] for row in rows}

    async def set_minigame_cooldown(
        self, guild_id: int, user_id: int, job: str, when: float
    ) -> None:
        await self.execute(
            "INSERT INTO minigame_cooldowns (guild_id, user_id, job, last_played) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (guild_id, user_id, job) "
            "DO UPDATE SET last_played = excluded.last_played",
            guild_id, user_id, job, when,
        )

    # ── skills ──────────────────────────────────────────────────────────

    async def get_skill(self, guild_id: int, user_id: int, job: str):
        # Fast path first, same reasoning as get_user.
        row = await self.fetchone(
            "SELECT * FROM skills WHERE guild_id = ? AND user_id = ? AND job = ?",
            guild_id, user_id, job,
        )
        if row is not None:
            return row
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
        # Postgres promotes SUM() over a BIGINT column to NUMERIC (Decimal
        # in Python) for overflow safety; cast back to a plain int so it
        # behaves identically to SQLite and doesn't break float math
        # downstream (formulas.py does 1.0 + rate * total_level, which
        # raises TypeError for float * Decimal).
        row = await self.fetchone(
            "SELECT COALESCE(CAST(SUM(level) AS BIGINT), 0) AS total FROM skills "
            "WHERE guild_id = ? AND user_id = ?",
            guild_id, user_id,
        )
        return int(row["total"])

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
        """Remove qty of an item; False if the user doesn't hold enough.
        Conditional, so two concurrent spends can't consume the same
        goods twice (e.g. .sell racing the Sell Haul button)."""
        removed = await self.execute_rowcount(
            "UPDATE inventory SET qty = qty - ? "
            "WHERE guild_id = ? AND user_id = ? AND item = ? AND qty >= ?",
            qty, guild_id, user_id, item, qty,
        )
        if not removed:
            return False
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
        """Ranked by total wealth (pocket + bank combined)."""
        return await self.fetchall(
            "SELECT user_id, gold, bank_gold, (gold + bank_gold) AS total_gold "
            "FROM users WHERE guild_id = ? AND (gold + bank_gold) > 0 "
            "ORDER BY total_gold DESC LIMIT ?",
            guild_id, limit,
        )

    async def top_skills(self, guild_id: int, limit: int = 10) -> list:
        return await self.fetchall(
            "SELECT user_id, CAST(SUM(level) AS BIGINT) AS total_level, "
            "MAX(level) AS best_level "
            "FROM skills WHERE guild_id = ? GROUP BY user_id "
            "ORDER BY total_level DESC LIMIT ?",
            guild_id, limit,
        )
