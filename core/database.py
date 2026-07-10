import aiosqlite
from loguru import logger

from config.settings import AppConfig


class Database:
    def __init__(self, config: AppConfig) -> None:
        db_url = config.database_url.replace("sqlite:///", "")
        self._db_path = str(config.database_url).replace("sqlite:///", "") if db_url else "dhn_pi.db"
        if self._db_path.startswith("sqlite:///"):
            self._db_path = self._db_path[10:]
        self._conn: aiosqlite.Connection | None = None

    @property
    def db_path(self) -> str:
        return self._db_path

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        logger.info(f"SQLite connected: {self._db_path}")

    async def initialize(self) -> None:
        """Run migrations / create initial tables. Add tables here as needed."""
        await self._execute("""
            CREATE TABLE IF NOT EXISTS _schema_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("Database schema initialized (empty)")

    async def disconnect(self) -> None:
        if self._conn:
            await self._conn.close()
            logger.info("SQLite disconnected")

    async def _execute(self, sql: str, params: tuple | None = None) -> aiosqlite.Cursor:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return await self._conn.execute(sql, params or ())

    async def execute(self, sql: str, params: tuple | None = None) -> aiosqlite.Cursor:
        return await self._execute(sql, params)

    async def fetchone(self, sql: str, params: tuple | None = None):
        cursor = await self._execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple | None = None):
        cursor = await self._execute(sql, params)
        return await cursor.fetchall()

    async def commit(self) -> None:
        if self._conn:
            await self._conn.commit()
