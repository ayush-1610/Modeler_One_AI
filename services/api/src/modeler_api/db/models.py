"""ORM models for the campaign tables (and the minimal core rows they reference).

Columns mirror services/api/migrations/0001_core.sql and 0002_campaigns.sql. The database owns defaults
(ids, timestamps) and every invariant the ORM cannot express — RLS, append-only triggers, check
constraints — so these models are for reading and writing rows, not for creating the schema.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from modeler_api.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    slug: Mapped[str]
    tenancy_mode: Mapped[str]
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    oidc_subject: Mapped[str]
    printed_name: Mapped[str]
    email: Mapped[str]
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    campaign_ref: Mapped[str]
    question_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    compound_name: Mapped[str]
    map_id: Mapped[str | None]
    engine_image_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    budget_seconds: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str]
    current_stage: Mapped[str | None]
    cpf_start_sha256: Mapped[str] = mapped_column(String(64))
    final_cpf_sha256: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class CampaignStage(Base):
    __tablename__ = "campaign_stages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    stage: Mapped[str]
    status: Mapped[str]
    budget_seconds: Mapped[int] = mapped_column(Integer)
    max_rounds: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))


class CampaignRound(Base):
    __tablename__ = "campaign_rounds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaign_stages.id"))
    round: Mapped[int] = mapped_column(Integer)
    cpf_before_sha256: Mapped[str] = mapped_column(String(64))
    cpf_after_sha256: Mapped[str] = mapped_column(String(64))
    action: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    verdict: Mapped[str]
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    stage_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaign_stages.id"))
    round_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaign_rounds.id"))
    reason_code: Mapped[str]
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    options: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    decided_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class Deviation(Base):
    __tablename__ = "deviations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    map_id: Mapped[str | None]
    kind: Mapped[str]
    rationale: Mapped[str]
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    signature_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
