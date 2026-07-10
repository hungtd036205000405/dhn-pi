import pytest
import asyncio
import os

from config.settings import AppConfig
from core.database import Database


@pytest.fixture
def db_config() -> AppConfig:
    return AppConfig(database_url="sqlite:///test_dhn_pi.db")


@pytest.fixture
async def database(db_config: AppConfig) -> Database:
    db = Database(db_config)
    await db.connect()
    await db.initialize()
    yield db
    await db.disconnect()
    if os.path.exists(db.db_path):
        os.remove(db.db_path)


@pytest.mark.asyncio
async def test_database_connect(database: Database) -> None:
    assert database._conn is not None


@pytest.mark.asyncio
async def test_database_schema_version(database: Database) -> None:
    row = await database.fetchone("SELECT COUNT(*) as cnt FROM _schema_version")
    assert row is not None
    assert row["cnt"] == 0


@pytest.mark.asyncio
async def test_database_execute_and_fetch(database: Database) -> None:
    await database.execute(
        "CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, name TEXT)"
    )
    await database.execute("INSERT INTO test_table (name) VALUES (?)", ("test_row",))
    await database.commit()

    row = await database.fetchone("SELECT * FROM test_table WHERE name = ?", ("test_row",))
    assert row is not None
    assert row["name"] == "test_row"

    rows = await database.fetchall("SELECT * FROM test_table")
    assert len(rows) == 1
