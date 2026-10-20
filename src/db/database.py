"""SQLite connection with explicit, serialized write transactions."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Self

import aiosqlite
from loguru import logger

__all__ = ["Database"]


class Database:
    """One shared aiosqlite connection in autocommit mode.

    Every write goes through ``transaction()``: it holds a lock so that two handlers
    never interleave statements inside the same SQLite transaction.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not open; use 'async with Database(...)'")
        return self._conn

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        await self._conn.execute("PRAGMA journal_mode = WAL")

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._write_lock:
            conn = self.conn
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
            await conn.execute("COMMIT")

    async def backup(self, label: str) -> Path:
        """Write a consistent copy next to the database file and return its path."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = self._path.with_name(f"{self._path.name}.bak-{label}-{stamp}")
        async with self._write_lock:
            await self.conn.execute("VACUUM INTO ?", (str(target),))
        logger.info("Database backup written to {}", target)
        return target
