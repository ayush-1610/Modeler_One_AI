"use client";

// Companies in the admin console (docs/plans/2026-11-10-admin-console.md, F): a new one (a tenant: its id is what its
// people carry and cannot change later), and one disabled (none of its people can sign in; nothing is erased) or
// enabled again with the same people. A reason and a fresh step-up each; events on the company's own audit trail.

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card } from "@/components/ui";
import { send } from "@/lib/api";

export function AddCompany() {
  const router = useRouter();
  const [tenant, setTenant] = useState("");
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function add() {
    setBusy(true);
    setProblem(null);
    const env = await send("post", "/api/v1/admin/companies", {}, { tenant_id: tenant.trim(), name: name.trim(), reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    router.push(`/admin/companies/${encodeURIComponent(env.data.tenant_id)}`);
  }

  return (
    <Card title="Add a company">
      <form className="admin-filter" onSubmit={(e) => { e.preventDefault(); void add(); }} data-testid="company-add">
        <label>Id (its people carry it; it cannot change)
          <input value={tenant} onChange={(e) => setTenant(e.target.value.toLowerCase())} placeholder="e.g. acme"
                 data-testid="company-id" /></label>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme Pharma"
                          data-testid="company-name" /></label>
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept on its audit trail"
                         data-testid="company-reason" /></label>
        <button type="submit" className="btn primary" disabled={busy || !tenant.trim() || !name.trim() || !reason.trim()}
                data-testid="company-add-submit">Add the company</button>
      </form>
      {problem && <div className="banner err" style={{ marginTop: 10 }} data-testid="company-problem">{problem}</div>}
    </Card>
  );
}

export function CompanyState({ tenantId, disabledReason }: { tenantId: string; disabledReason: string | null }) {
  const router = useRouter();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const disabled = disabledReason !== null;

  async function toggle() {
    setBusy(true);
    setProblem(null);
    const path = disabled ? "/api/v1/admin/companies/{tenant_id}:enable" : "/api/v1/admin/companies/{tenant_id}:disable";
    const env = await send("post", path, { tenant_id: tenantId }, { reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    router.refresh();
  }

  return (
    <Card title={disabled ? "This company is disabled" : "Disable this company"}>
      <p className="muted" style={{ marginTop: 0 }}>
        {disabled
          ? `Why: ${disabledReason}. Enabling it lets the same people sign in again (not those disabled on their own).`
          : "None of its people can sign in afterwards (their open sessions end within minutes). Its projects, records and people are kept; enabling it later lets the same people in again."}
      </p>
      <div className="admin-filter">
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept on its audit trail"
                         data-testid="company-state-reason" /></label>
        <button type="button" className={`btn ${disabled ? "primary" : ""}`} disabled={busy || !reason.trim()}
                onClick={() => void toggle()} data-testid="company-state-submit">
          {disabled ? "Enable the company" : "Disable the company"}
        </button>
      </div>
      {problem && <div className="banner err" style={{ marginTop: 10 }}>{problem}</div>}
    </Card>
  );
}
