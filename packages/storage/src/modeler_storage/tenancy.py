"""Tenant binding for database sessions.

saas-pooled: one database, row-level security keyed on ``app.tenant_id`` (see migrations/0001_core.sql).
cro-silo:    one database per client; the session factory is chosen per tenant, RLS still applies.
onprem-single: one tenant; RLS still applies so the same migrations and queries run everywhere.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def bind_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Scope the current transaction to one tenant. Must run before any tenant-owned query."""
    await session.execute(text("SELECT set_config('app.tenant_id', :tenant_id, true)"), {"tenant_id": str(tenant_id)})
