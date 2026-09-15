-- Modeler One core schema (PostgreSQL 16).
-- Tenant isolation via row-level security on app.tenant_id; compliance tables are append-only.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE tenants (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug          text NOT NULL UNIQUE,
  tenancy_mode  text NOT NULL CHECK (tenancy_mode IN ('saas-pooled', 'cro-silo', 'onprem-single')),
  created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  oidc_subject  text NOT NULL,
  printed_name  text NOT NULL,
  email         text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, oidc_subject)
);

CREATE TABLE engine_images (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  digest              text NOT NULL UNIQUE,
  engine_id           text NOT NULL,
  snapshot_versions   int[] NOT NULL,
  status              text NOT NULL CHECK (status IN ('BUILT', 'QUALIFIED', 'RETIRED')),
  qualified_contexts  text[] NOT NULL DEFAULT '{}',
  created_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE model_versions (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id                uuid NOT NULL REFERENCES tenants(id),
  compound_name            text NOT NULL,
  snapshot_sha256          char(64) NOT NULL,
  parent_sha256            char(64),
  snapshot_schema_version  int NOT NULL,
  engine_image_id          uuid REFERENCES engine_images(id),
  status                   text NOT NULL DEFAULT 'DRAFT'
                           CHECK (status IN ('DRAFT', 'EVALUATED', 'LOCKED', 'SUPERSEDED', 'QUARANTINED')),
  object_key               text NOT NULL,
  validation               jsonb NOT NULL DEFAULT '[]',
  created_by               uuid REFERENCES users(id),
  created_at               timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, snapshot_sha256)
);

CREATE TABLE parameter_provenance (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         uuid NOT NULL REFERENCES tenants(id),
  model_version_id  uuid NOT NULL REFERENCES model_versions(id),
  locator           jsonb NOT NULL,
  value             double precision NOT NULL,
  unit              text,
  source_type       text NOT NULL CHECK (source_type IN
                    ('InVitro', 'Publication', 'Database', 'ParameterIdentification', 'Assumption', 'Internal', 'Allometry', 'Calculated')),
  citation          jsonb,
  conditions        jsonb,
  justification     text,
  state             text NOT NULL DEFAULT 'PROPOSED' CHECK (state IN ('PROPOSED', 'ACCEPTED', 'REJECTED')),
  proposed_by       text NOT NULL,          -- user id or agent_run id
  decided_by        uuid REFERENCES users(id),
  supersedes_id     uuid REFERENCES parameter_provenance(id),
  created_at        timestamptz NOT NULL DEFAULT now(),
  CHECK (source_type <> 'Assumption' OR length(coalesce(justification, '')) >= 50)
);

CREATE TABLE runs (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id            uuid NOT NULL REFERENCES tenants(id),
  model_version_id     uuid NOT NULL REFERENCES model_versions(id),
  task                 text NOT NULL,
  options_hash         char(64) NOT NULL,
  seed                 bigint,
  engine_image_digest  text NOT NULL,
  status               text NOT NULL,
  manifest_key         text,
  requested_by         uuid REFERENCES users(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  finished_at          timestamptz
);
-- Memoization: an identical request reuses the existing run.
CREATE UNIQUE INDEX runs_memo ON runs (tenant_id, model_version_id, task, engine_image_digest, options_hash, coalesce(seed, -1));

CREATE TABLE signatures (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  signer_id      uuid NOT NULL REFERENCES users(id),
  printed_name   text NOT NULL,
  meaning        text NOT NULL CHECK (meaning IN ('Authored', 'Reviewed', 'Approved', 'QA Released')),
  signed_at      timestamptz NOT NULL,
  record_type    text NOT NULL,
  record_id      uuid NOT NULL,
  record_sha256  char(64) NOT NULL,
  auth_method    text NOT NULL
);

CREATE TABLE audit_events (
  tenant_id      uuid NOT NULL REFERENCES tenants(id),
  seq            bigint NOT NULL,
  occurred_at    timestamptz NOT NULL,
  actor          text NOT NULL,
  action         text NOT NULL,
  resource_type  text NOT NULL,
  resource_id    text NOT NULL,
  before         jsonb,
  after          jsonb,
  reason         text,
  request_id     text,
  prev_hash      char(64) NOT NULL,
  row_hash       char(64) NOT NULL,
  PRIMARY KEY (tenant_id, seq)
);

-- Append-only enforcement
CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$;

CREATE TRIGGER audit_events_append_only BEFORE UPDATE OR DELETE ON audit_events
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
  FOR EACH STATEMENT EXECUTE FUNCTION reject_mutation();
CREATE TRIGGER signatures_append_only BEFORE UPDATE OR DELETE ON signatures
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- Snapshot content of a model version never changes; status transitions are the only update.
CREATE FUNCTION protect_model_version_content() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256
     OR NEW.object_key IS DISTINCT FROM OLD.object_key
     OR NEW.snapshot_schema_version IS DISTINCT FROM OLD.snapshot_schema_version
     OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
    RAISE EXCEPTION 'model version content is immutable; create a new version';
  END IF;
  IF OLD.status IN ('LOCKED', 'SUPERSEDED') AND NEW.status NOT IN ('SUPERSEDED') THEN
    RAISE EXCEPTION 'locked model versions can only be superseded';
  END IF;
  RETURN NEW;
END
$$;
CREATE TRIGGER model_versions_immutable BEFORE UPDATE ON model_versions
  FOR EACH ROW EXECUTE FUNCTION protect_model_version_content();
CREATE TRIGGER model_versions_no_delete BEFORE DELETE ON model_versions
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

-- Row-level security
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['users', 'model_versions', 'parameter_provenance', 'runs', 'signatures', 'audit_events'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'')::uuid) '
      'WITH CHECK (tenant_id = current_setting(''app.tenant_id'')::uuid)', t);
  END LOOP;
END
$$;

REVOKE UPDATE, DELETE, TRUNCATE ON audit_events, signatures FROM PUBLIC;
