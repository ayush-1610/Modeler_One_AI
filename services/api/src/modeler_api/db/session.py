"""Async engine and the tenant-scoped session that every repository call runs inside."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from modeler_api.tenancy import bind_tenant


class Database:
    """Owns the async engine and session factory for one database URL."""

    def __init__(self, url: str, *, echo: bool = False):
        self._engine: AsyncEngine = create_async_engine(url, echo=echo, pool_pre_ping=True)
        self._sessions = async_sessionmaker(self._engine, expire_on_commit=False, class_=AsyncSession)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def tenant_session(self, tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session, session.begin():
            await bind_tenant(session, tenant_id)
            yield session

    async def dispose(self) -> None:
        await self._engine.dispose()


@asynccontextmanager
async def tenant_session(sessions: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Open a session, begin a transaction, bind the tenant (RLS), and commit on success / roll back on error."""
    async with sessions() as session, session.begin():
        await bind_tenant(session, tenant_id)
        yield session
