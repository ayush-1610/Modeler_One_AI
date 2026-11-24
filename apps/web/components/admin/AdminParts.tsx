import Link from "next/link";
import type { ReactNode } from "react";

import { Card } from "@/components/ui";
import { PRICED_AS, percent, tokens, usd, when, type LimitRow, type PricedAs, type Usage, type UsageGroup } from "@/lib/admin";

/** On the pages with costs, the model the costs are priced at: a link per model, since the page is read on the server.
 *  The console's pages themselves are in the side navigation (the console redesign: slice 1, the tabs removed in 8). */
export function PricingSwitch({ priced = "claude-opus-5-5", base, query = {} }: {
  priced?: PricedAs; base: string; query?: Record<string, string | undefined>;
}) {
  const href = (p: PricedAs) => {
    const given: Record<string, string | undefined> = { ...query, priced_as: p };
    const params = new URLSearchParams(Object.entries(given).filter((e): e is [string, string] => Boolean(e[1])));
    return `${base}?${params.toString()}`;
  };
  return (
    <div className="pricing-switch" data-testid="priced-as">
      <span className="muted fs-13">Costs as if run on</span>
      <div className="view-switch" role="group" aria-label="Costs priced as">
        {PRICED_AS.map((p) => (
          <Link key={p.id} href={href(p.id)} prefetch={false} aria-current={p.id === priced ? "true" : undefined}
                className={p.id === priced ? "on" : undefined}>{p.label}</Link>
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

/** What a limit's level reads as: reached (100 %), or near it (80 %). */
export function LimitLevel({ row }: { row: LimitRow }) {
  const tone = row.level === "over" ? "high" : row.level === "warn" ? "medium" : "low";
  const text = row.level === "over" ? "reached" : row.level === "warn" ? "near" : "within";
  return <span className={`chip ${tone}`} data-testid={`limit-level-${row.id}`}><span className="chip-dot" />{text}</span>;
}

/** The limits this month's use is near (80 %) or has reached: for the administrator alone. Agents keep running. */
export function LimitWarnings({ warnings, month, priced }: { warnings: LimitRow[]; month: string; priced: PricedAs }) {
  if (warnings.length === 0) return null;
  const reached = warnings.some((w) => w.level === "over");
  return (
    <div className={`banner ${reached ? "err" : "warn"} mb-16`} data-testid="limit-warnings">
      <strong>{reached ? "A monthly limit is reached" : "A monthly limit is near"}</strong> ({month}; you are warned at 80 % and
      at 100 %; the agents keep running, and the companies&apos; people see nothing of it):
      <ul className="plain-list m-6-0-0">
        {warnings.map((w) => (
          <li key={w.id} data-testid={`limit-warning-${w.id}`}>
            <strong>{w.level === "over" ? "reached" : "near"}</strong> · {w.label}, {w.scope}:{" "}
            {[w.usd !== null && `spend ${usd(w.used_usd)} of ${usd(w.usd)} (${percent(w.usd_share)})`,
              w.tokens !== null && `tokens ${tokens(w.used_tokens)} of ${tokens(w.tokens)} (${percent(w.tokens_share)})`]
              .filter(Boolean).join("; ")}
          </li>
        ))}
      </ul>
      <Link href={`/admin/limits?priced_as=${priced}`}>Open the limits</Link>
    </div>
  );
}
