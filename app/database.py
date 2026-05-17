import logging
import os

import aiosqlite

from app.config import settings

logger = logging.getLogger(__name__)

_db_connection: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """Get the shared aiosqlite connection, creating it on first call."""
    global _db_connection
    if _db_connection is None:
        os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
        _db_connection = await aiosqlite.connect(settings.db_path)
        _db_connection.row_factory = aiosqlite.Row
        await _db_connection.execute("PRAGMA journal_mode=WAL")
        await _db_connection.execute("PRAGMA foreign_keys=ON")
        await _db_connection.execute("PRAGMA synchronous=NORMAL")
    return _db_connection


async def init_db() -> None:
    """Run all pending migrations."""
    db = await get_db()
    await _run_migrations(db)
    logger.info("Database initialized successfully")


async def _run_migrations(db: aiosqlite.Connection) -> None:
    """Discover and run migration files from the migrations/ directory."""
    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
    migrations_dir = os.path.normpath(migrations_dir)

    if not os.path.isdir(migrations_dir):
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return

    # Ensure schema version table exists
    await db.execute(
        "CREATE TABLE IF NOT EXISTS _schema_version (version INTEGER PRIMARY KEY)"
    )
    cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM _schema_version")
    row = await cursor.fetchone()
    current_version: int = row[0] if row else 0

    # Discover migration files sorted by name
    migration_files = sorted(
        f for f in os.listdir(migrations_dir) if f.endswith(".sql")
    )

    for filename in migration_files:
        version = int(filename.split("_")[0])
        if version <= current_version:
            continue

        filepath = os.path.join(migrations_dir, filename)
        with open(filepath, "r") as f:
            sql = f.read()

        logger.info("Running migration: %s", filename)
        await db.executescript(sql)
        await db.execute("INSERT INTO _schema_version (version) VALUES (?)", (version,))

    await db.commit()
