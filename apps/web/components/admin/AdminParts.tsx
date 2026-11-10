import Link from "next/link";
import type { ReactNode } from "react";

import { Card } from "@/components/ui";
import { PRICED_AS, tokens, usd, when, type PricedAs, type Usage, type UsageGroup } from "@/lib/admin";

/** The console's three pages, and the model its costs are priced at (a link per model: the page is read on the server). */
export function AdminTabs({ here, priced, base, query = {} }: {
  here: "overview" | "usage" | "company"; priced: PricedAs; base: string; query?: Record<string, string | undefined>;
}) {
  const href = (p: PricedAs) => {
    const given: Record<string, string | undefined> = { ...query, priced_as: p };
    const params = new URLSearchParams(Object.entries(given).filter((e): e is [string, string] => Boolean(e[1])));
    return `${base}?${params.toString()}`;
  };
  return (
    <div className="spread" style={{ marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
      <nav className="tabs" aria-label="Admin console" data-testid="admin-tabs">
        <Link href={`/admin?priced_as=${priced}`} className={here === "overview" ? "active" : ""}>Overview</Link>
        <Link href={`/admin/usage?priced_as=${priced}`} className={here === "usage" ? "active" : ""}>Usage and cost</Link>
      </nav>
      <div className="muted" data-testid="priced-as">
        Costs as if run on{" "}
        {PRICED_AS.map((p, i) => (
          <span key={p.id}>
            {i > 0 && " · "}
            {p.id === priced ? <strong>{p.label}</strong> : <Link href={href(p.id)}>{p.label}</Link>}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Runs, failed runs, tokens and the estimated cost, side by side. */
export function UsageKpis({ usage }: { usage: Usage }) {
  const items: [string, ReactNode][] = [
    ["agent runs", usage.runs], ["did not finish", usage.failed_runs], ["input tokens", tokens(usage.input_tokens)],
    ["output tokens", tokens(usage.output_tokens)], ["estimated cost, cached", usd(usage.usd)],
    ["last run", when(usage.last_run_at)],
  ];
  return (
    <div className="kpi" data-testid="usage-kpis">
      {items.map(([label, value]) => <div className="k" key={label}><div className="v">{value}</div><div className="l">{label}</div></div>)}
    </div>
  );
}

export function UsageCells({ usage }: { usage: Usage }) {
  return (
    <>
      <td className="num">{usage.runs}</td>
      <td className="num">{usage.failed_runs || "—"}</td>
      <td className="num">{tokens(usage.input_tokens)}</td>
      <td className="num">{tokens(usage.output_tokens)}</td>
      <td className="num">{usd(usage.usd)}</td>
    </>
  );
}

export const USAGE_HEADS = (
  <>
    <th className="num">Runs</th><th className="num">Did not finish</th><th className="num">Input</th>
    <th className="num">Output</th><th className="num">Est. cost</th>
  </>
);

/** One grouping of the usage (per agent, project, person, company or day). */
export function UsageTable({ title, column, rows, testId }: { title: string; column: string; rows: UsageGroup[]; testId: string }) {
  return (
    <Card title={title}>
      {rows.length === 0 ? <p className="muted">No runs.</p> : (
        <div className="table-scroll">
          <table data-testid={testId}>
            <thead><tr><th>{column}</th>{USAGE_HEADS}</tr></thead>
            <tbody>
              {rows.map((r) => <tr key={r.key}><td>{r.label}</td><UsageCells usage={r.usage} /></tr>)}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** What a person who is not the platform's owner sees: the API refused them. */
export function NotForYou() {
  return (
    <Card>
      <p data-testid="admin-refused">
        The admin console is for the platform&apos;s owner only (the <code>modeler-admin</code> role). Your sign-in does not
        hold it.
      </p>
    </Card>
  );
}
