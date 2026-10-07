from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base. Tables are created by the SQL migrations (services/api/migrations), never by
    metadata.create_all — the migrations carry the RLS policies, append-only triggers and check
    constraints that the ORM models do not express."""
