-- Modeler One agent persistence (task T-20). Every agent invocation, every model turn and every parameter
-- proposal is recorded so the audit viewer can show exactly what each agent did and why. Tenant isolation via
-- RLS on app.tenant_id (as 0001_core.sql); agent_steps and proposals are append-only.

CREATE TABLE agent_runs (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       uuid NOT NULL REFERENCES tenants(id),
  agent           text NOT NULL,                       -- "strategist", "parameter_curation", "literature", ...
  campaign_id     uuid REFERENCES campaigns(id),       -- null for intake/curation runs outside a campaign
  provider        text NOT NULL,                       -- anthropic | bedrock | vertex | self_hosted
  model           text NOT NULL,
  status          text NOT NULL DEFAULT 'RUNNING'
                  CHECK (status IN ('RUNNING', 'COMPLETED', 'INCOMPLETE', 'REFUSED', 'LLM_UNAVAILABLE')),
  input_tokens    bigint NOT NULL DEFAULT 0,
  output_tokens   bigint NOT NULL DEFAULT 0,
  cost_usd        numeric(12, 6) NOT NULL DEFAULT 0,
  budget          jsonb NOT NULL DEFAULT '{}',         -- the limits this run was given
  summary         jsonb NOT NULL DEFAULT '{}',
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz
);

-- Append-only: one immutable record per model turn (assistant message or tool result).
CREATE TABLE agent_steps (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  run_id        uuid NOT NULL REFERENCES agent_runs(id),
  seq           int NOT NULL,
  kind          text NOT NULL,                          -- "assistant" | "tool_use" | "tool_result" | "decision"
  content       jsonb NOT NULL DEFAULT '{}',
  usage         jsonb NOT NULL DEFAULT '{}',            -- input/output tokens for this turn
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, run_id, seq)
);

-- Append-only: parameter proposals the curator later accepts or rejects (status transitions recorded in audit).
CREATE TABLE proposals (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     uuid NOT NULL REFERENCES tenants(id),
  run_id        uuid NOT NULL REFERENCES agent_runs(id),
  parameter_id  text NOT NULL,
  value         text,
  unit          text,
  citation      jsonb NOT NULL DEFAULT '{}',
  status        text NOT NULL DEFAULT 'PROPOSED'
                CHECK (status IN ('PROPOSED', 'ACCEPTED', 'REJECTED')),
  decided_by    uuid REFERENCES users(id),
  decided_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- agent_steps is append-only; proposals rows are immutable except for the curator decision, so only agent_steps
-- gets the reject_mutation trigger. Proposal decisions are applied with an UPDATE guarded at the application layer.
CREATE TRIGGER agent_steps_append_only BEFORE UPDATE OR DELETE ON agent_steps
  FOR EACH ROW EXECUTE FUNCTION reject_mutation();

CREATE INDEX agent_steps_run ON agent_steps (tenant_id, run_id, seq);
CREATE INDEX proposals_run ON proposals (tenant_id, run_id);
CREATE INDEX agent_runs_campaign ON agent_runs (tenant_id, campaign_id);

-- Row-level security, keyed on app.tenant_id.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['agent_runs', 'agent_steps', 'proposals'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (tenant_id = current_setting(''app.tenant_id'')::uuid) '
      'WITH CHECK (tenant_id = current_setting(''app.tenant_id'')::uuid)', t);
  END LOOP;
END
$$;

REVOKE UPDATE, DELETE, TRUNCATE ON agent_steps FROM PUBLIC;
