"use client";

// The realm's people, kept in Keycloak and changed here as its service account (docs/plans/2026-11-10-admin-console.md,
// F): added to a company with their roles, disabled, given or taken roles, moved, a lost authenticator reset. Every
// change needs a reason and a fresh step-up. No password is ever typed here: a new person sets their own through
// Keycloak's email, or the owner sets a temporary one in Keycloak's own console (the link this page gives).

import { useMemo, useState } from "react";

import { Card } from "@/components/ui";
import { send, type Schema } from "@/lib/api";
import { when } from "@/lib/admin";

type Page = Schema<"PeoplePage">;
type Person = Page["people"][number];

const ROLE_LABEL: Record<string, string> = {
  "modeler-viewer": "viewer", "modeler-curator": "curator", "modeler-reviewer": "reviewer", "modeler-qa": "QA",
  "modeler-admin": "platform owner",
};
const ACTION_LABEL: Record<string, string> = {
  UPDATE_PASSWORD: "set a password", CONFIGURE_TOTP: "set up the authenticator", VERIFY_EMAIL: "verify their email",
};

function Problem({ text }: { text: string | null }) {
  return text ? <div className="banner err" style={{ marginTop: 10 }} data-testid="people-problem">{text}</div> : null;
}

function RoleBoxes({ roles, chosen, onChange, prefix }: {
  roles: string[]; chosen: string[]; onChange: (r: string[]) => void; prefix: string;
}) {
  return (
    <>
      {roles.map((r) => (
        <label key={r} className="check">
          <input type="checkbox" checked={chosen.includes(r)} data-testid={`${prefix}-${r}`}
                 onChange={(e) => onChange(e.target.checked ? [...chosen, r] : chosen.filter((x) => x !== r))} />
          {ROLE_LABEL[r] ?? r}
        </label>
      ))}
    </>
  );
}

function AddPerson({ page, onDone }: { page: Page; onDone: (p: Page) => void }) {
  const [tenant, setTenant] = useState(page.companies[0] ?? "");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [roles, setRoles] = useState<string[]>(["modeler-viewer", "modeler-curator"]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const ready = tenant && username.trim() && email.includes("@") && first.trim() && last.trim() && roles.length && reason.trim();

  async function add() {
    setBusy(true);
    setProblem(null);
    const env = await send("post", "/api/v1/admin/people", {}, {
      username: username.trim().toLowerCase(), email: email.trim(), first_name: first.trim(), last_name: last.trim(),
      tenant_id: tenant, roles, reason: reason.trim() });
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setUsername(""); setEmail(""); setFirst(""); setLast(""); setReason("");
    onDone(env.data);
  }

  return (
    <Card title="Add a person">
      <p className="muted" style={{ marginTop: 0 }}>
        They are created in Keycloak and set their own password and authenticator at their first sign-in.{" "}
        {page.smtp ? "Keycloak emails them the link." : "Keycloak has no mail server: the next step is a temporary password you set in Keycloak's own console (the link appears here)."}
      </p>
      <form className="admin-filter" autoComplete="off" onSubmit={(e) => { e.preventDefault(); void add(); }} data-testid="person-add">
        <label>Company
          <select value={tenant} onChange={(e) => setTenant(e.target.value)} data-testid="person-tenant">
            {page.companies.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} data-testid="person-username" /></label>
        <label>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="person-email" /></label>
        <label>First name<input value={first} onChange={(e) => setFirst(e.target.value)} data-testid="person-first" /></label>
        <label>Last name<input value={last} onChange={(e) => setLast(e.target.value)} data-testid="person-last" /></label>
        <RoleBoxes roles={page.roles} chosen={roles} onChange={setRoles} prefix="person-role" />
        <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept on the company's audit trail"
                         data-testid="person-reason" /></label>
        <button type="submit" className="btn primary" disabled={busy || !ready} data-testid="person-add-submit">Add the person</button>
      </form>
      <Problem text={problem} />
    </Card>
  );
}

function PersonEditor({ person, page, onDone }: { person: Person; page: Page; onDone: (p: Page) => void }) {
  const given = person.roles.filter((r) => page.roles.includes(r));
  const [roles, setRoles] = useState<string[]>(given);
  const [tenant, setTenant] = useState(person.tenant_id);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function act(path: "/api/v1/admin/people/{user_id}:change" | "/api/v1/admin/people/{user_id}:reset", body: object) {
    setBusy(true);
    setProblem(null);
    const env = await send("post", path, { user_id: person.id }, { ...body, reason: reason.trim() } as never);
    setBusy(false);
    if (env.errors?.length || !env.data) { setProblem(env.errors?.[0]?.message ?? "no answer"); return; }
    setReason("");
    onDone(env.data);
  }
  const changes = {
    add_roles: roles.filter((r) => !given.includes(r)), remove_roles: given.filter((r) => !roles.includes(r)),
    ...(tenant !== person.tenant_id ? { tenant_id: tenant } : {}),
  };
  const changed = changes.add_roles.length > 0 || changes.remove_roles.length > 0 || tenant !== person.tenant_id;
  const why = Boolean(reason.trim()) && !busy;

  return (
    <div className="admin-filter" style={{ marginTop: 8 }} data-testid={`person-editor-${person.username}`}>
      <RoleBoxes roles={page.roles} chosen={roles} onChange={setRoles} prefix={`person-${person.username}-role`} />
      <label>Company
        <select value={tenant} onChange={(e) => setTenant(e.target.value)} data-testid={`person-${person.username}-tenant`}>
          {[...new Set([person.tenant_id, ...page.companies])].filter(Boolean).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      <label>Why<input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="kept with the change"
                       data-testid={`person-${person.username}-reason`} /></label>
      <button type="button" className="btn primary" disabled={!why || !changed} onClick={() => void act("/api/v1/admin/people/{user_id}:change", changes)}
              data-testid={`person-${person.username}-save`}>Save</button>
      <button type="button" className="btn" disabled={!why} data-testid={`person-${person.username}-enable`}
              onClick={() => void act("/api/v1/admin/people/{user_id}:change", { enabled: !person.enabled })}>
        {person.enabled ? "Disable" : "Enable"}
      </button>
      <button type="button" className="btn" disabled={!why} data-testid={`person-${person.username}-reset-totp`}
              onClick={() => void act("/api/v1/admin/people/{user_id}:reset", { authenticator: true })}>Reset authenticator</button>
      <button type="button" className="btn" disabled={!why} data-testid={`person-${person.username}-reset-password`}
              onClick={() => void act("/api/v1/admin/people/{user_id}:reset", { password: true })}>New password</button>
      <Problem text={problem} />
    </div>
  );
}

export function People({ initial }: { initial: Page }) {
  const [page, setPage] = useState(initial);
  const [company, setCompany] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const shown = useMemo(() => page.people.filter((p) => !company || p.tenant_id === company), [page.people, company]);

  if (!page.ready) {
    return (
      <Card title="Keycloak is not set up for the console yet">
        <div className="banner warn" data-testid="people-not-ready">{page.problem}</div>
        <ol className="muted" style={{ marginBottom: 0 }}>
          <li>In Keycloak (realm <strong>modeler</strong>), create the client <code>{page.service_client}</code> with only
            &ldquo;Service accounts roles&rdquo;, and give its service account <code>realm-management</code>&apos;s
            manage-users, query-users, view-realm and view-users (deploy/keycloak/README.md).</li>
          <li>Here, under <strong>Keys</strong>: add a key of provider &ldquo;Keycloak service account&rdquo; with its client
            secret, test it, make it active.</li>
        </ol>
      </Card>
    );
  }

  return (
    <>
      {page.notice && (
        <div className="banner ok" style={{ marginBottom: 16 }} data-testid="people-notice">
          {page.notice}{" "}
          {page.notice_link && <a href={page.notice_link} target="_blank" rel="noreferrer" data-testid="people-notice-link">Open their page in Keycloak</a>}
        </div>
      )}
      <AddPerson page={page} onDone={setPage} />
      <Card title="People">
        <div className="admin-filter" style={{ marginBottom: 10 }}>
          <label>Company
            <select value={company} onChange={(e) => setCompany(e.target.value)} data-testid="people-filter">
              <option value="">every company</option>
              {page.companies.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
        </div>
        <div className="table-scroll">
          <table data-testid="admin-people-list">
            <thead><tr><th>Person</th><th>Company</th><th>Roles</th><th>Sign-in</th><th>Added</th><th /></tr></thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.id} data-testid={`person-${p.username}`}>
                  <td>
                    {p.name}<div className="muted">{p.username} · {p.email || "no email"}</div>
                    {open === p.id && <PersonEditor person={p} page={page} onDone={(next) => { setPage(next); setOpen(null); }} />}
                  </td>
                  <td>{p.tenant_id || <span className="muted">none</span>}</td>
                  <td>{p.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ") || "—"}</td>
                  <td>
                    <span className={`chip ${p.enabled ? "low" : "high"}`}><span className="chip-dot" />{p.enabled ? "can sign in" : "disabled"}</span>
                    <div className="muted">{p.authenticator ? "authenticator set up" : "no authenticator yet"}</div>
                    {p.required_actions.length > 0 && (
                      <div className="muted">next sign-in: {p.required_actions.map((a) => ACTION_LABEL[a] ?? a).join(", ")}</div>
                    )}
                  </td>
                  <td>{when(p.created_at)}</td>
                  <td>
                    <button type="button" className="btn" onClick={() => setOpen(open === p.id ? null : p.id)}
                            data-testid={`person-${p.username}-open`}>{open === p.id ? "Close" : "Change"}</button>
                    <div><a href={p.console_link} target="_blank" rel="noreferrer" className="muted">in Keycloak</a></div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ marginBottom: 0 }}>
          The platform owner&apos;s role (<code>modeler-admin</code>) is given only in Keycloak&apos;s own console. People are
          disabled, never deleted. You cannot disable or move yourself here.
        </p>
      </Card>
    </>
  );
}
