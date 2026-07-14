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
        """Run migrations / create initial tables."""
        await self._execute("""
            CREATE TABLE IF NOT EXISTS _schema_version (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                recording INTEGER DEFAULT 0,
                recording_started_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL CHECK(source_type IN ('webcam', 'ip')),
                device_index INTEGER,
                rtsp_url TEXT,
                width INTEGER DEFAULT 640,
                height INTEGER DEFAULT 480,
                fps INTEGER DEFAULT 15,
                enabled INTEGER DEFAULT 1,
                auto_detected INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await self._execute("ALTER TABLE cameras ADD COLUMN auto_detected INTEGER DEFAULT 0")
        except Exception:
            pass
        await self._execute("""
            CREATE TABLE IF NOT EXISTS position_cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
                camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(position_id, camera_id)
            )
        """)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS position_uxtx (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL UNIQUE REFERENCES positions(id) ON DELETE CASCADE,
                device_type TEXT NOT NULL CHECK(device_type IN ('gpio', 'uxtx')),
                gpio_pin INTEGER,
                uxtx_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await self._execute("""
            CREATE TABLE IF NOT EXISTS recording_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
                camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                stopped_at TIMESTAMP,
                duration_seconds REAL
            )
        """)
        logger.info("Database schema initialized: positions, cameras, position_cameras, position_uxtx, recording_files")

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
