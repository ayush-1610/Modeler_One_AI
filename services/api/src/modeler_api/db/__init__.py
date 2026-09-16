"""Async persistence: SQLAlchemy models, a tenant-scoped session, and repositories (task T-05).

Every tenant-owned write goes through a session bound to one tenant (`SET app.tenant_id`, enforced by
row-level security) and records an audit event in the same transaction, so a change and its audit trail
commit or roll back together.
"""

from modeler_api.db.base import Base
from modeler_api.db.session import Database, tenant_session

__all__ = ["Base", "Database", "tenant_session"]
