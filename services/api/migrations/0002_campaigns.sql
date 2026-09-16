-- Modeler One campaign persistence (task T-05, supports the T-13 workflows).
-- Tables from ENGINEERING_PLAN §5.4. Tenant isolation via RLS on app.tenant_id (as 0001_core.sql).
-- Append-only: campaign_rounds, deviations. References to tables not yet created (questions_of_interest,
-- cpf_versions, maps) are kept as plain columns for now; their foreign keys are added when those tables land.

CREATE TABLE campaigns (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id             uuid NOT NULL REFERENCES tenants(id),
  campaign_ref          text NOT NULL,                       -- workflow-facing campaign id
  question_id           uuid,                                -- FK -> questions_of_interest (later)
  compound_name         text NOT NULL,
  map_id                text,
  engine_image_id       uuid REFERENCES engine_images(id),
  budget_seconds        int NOT NULL DEFAULT 3600,
  seed                  bigint NOT NULL DEFAULT 1,
  status                text NOT NULL DEFAULT 'RUNNING'
                        CHECK (status IN ('RUNNING', 'COMPLETED', 'ESCALATED', 'REJECTED')),
  current_stage         text,
  cpf_start_sha256      char(64) NOT NULL,
  final_cpf_sha256      char(64),
  started_at            timestamptz NOT NULL DEFAULT now(),
  finished_at           timestamptz,
  UNIQUE (tenant_id, campaign_ref)
);

CREATE TABLE campaign_stages (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  campaign_id   uuid NOT NULL REFERENCES campaigns(id),
  stage         text NOT NULL,
  status        text NOT NULL DEFAULT 'RUNNING'
                CHECK (status IN ('RUNNING', 'PASSED', 'ACCEPTED', 'ESCALATED', 'ABORTED', 'FAILED')),
  budget_seconds int NOT NULL,
  max_rounds    int NOT NULL,
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  summary       jsonb NOT NULL DEFAULT '{}',
  UNIQUE (tenant_id, campaign_id, stage)
);

-- Append-only: one immutable record per modeling round.
CREATE TABLE campaign_rounds (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid NOT NULL REFERENCES tenants(id),
  stage_id          uuid NOT NULL REFERENCES campaign_stages(id),
  round             int NOT NULL,
  cpf_before_sha256 char(64) NOT NULL,
  cpf_after_sha256  char(64) NOT NULL,
  action            jsonb,
  diagnostics       jsonb,
  metrics           jsonb NOT NULL DEFAULT '{}',
  verdict           text NOT NULL,
  model_version_id  uuid REFERENCES model_versions(id),
  started_at        timestamptz NOT NULL DEFAULT now(),
  finished_at       timestamptz,
  UNIQUE (tenant_id, stage_id, round)
);

CREATE TABLE escalations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  campaign_id   uuid NOT NULL REFERENCES campaigns(id),
  stage_id      uuid REFERENCES campaign_stages(id),
  round_id      uuid REFERENCES campaign_rounds(id),
  reason_code   text NOT NULL,
  evidence      jsonb,
  options       jsonb,
  decision      jsonb,
  decided_by    uuid REFERENCES users(id),
  decided_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Append-only: MAP deviations, each with a decision and (later) a signature.
CREATE TABLE deviations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  campaign_id   uuid NOT NULL REFERENCES campaigns(id),
  map_id        text,
  kind          text NOT NULL,
  rationale     text NOT NULL,
  decided_by    uuid REFERENCES users(id),
  signature_id  uuid REFERENCES signatures(id),
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Append-only enforcement (reject_mutation defined in 0001_core.sql).
CREATE TRIGGER campaign_rounds_append_only BEFORE UPDATE OR DELETE ON campaign_rounds
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER deviations_append_only BEFORE UPDATE OR DELETE ON deviations
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- Row-level security, keyed on app.tenant_id.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['campaigns', 'campaign_stages', 'campaign_rounds', 'escalations', 'deviations'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'')::uuid) '
      'WITH CHECK (tenant_id = current_setting(''app.tenant_id'')::uuid)', t);
  END LOOP;
END
$$;

REVOKE UPDATE, DELETE, TRUNCATE ON campaign_rounds, deviations FROM PUBLIC;
