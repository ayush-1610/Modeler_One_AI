import Link from "next/link";

import { LimitWarnings, PricingSwitch, UsageKpis } from "@/components/admin/AdminParts";
import { ApiProblem, Hero } from "@/components/kit";
import { Panel } from "@/components/kit/Panel";
import { getOverview, hideUnlessAdmin, pricedAs } from "@/lib/admin";

const LEDE = "The platform at a glance: the limits reached, what every company's agents used, and what the platform runs on. " +
  "Read-only: each look is recorded on the audit trail.";

/** The platform owner's console, its overview (docs/plans/2026-11-10-admin-console.md, build A; the console redesign's
 *  slice 8: the companies are their own page, P-24). */
export default async function AdminPage({ searchParams }: { searchParams: Promise<{ priced_as?: string }> }) {
  const priced = pricedAs((await searchParams).priced_as);
  const live = await getOverview(priced);
  hideUnlessAdmin(live.problem);
  const data = live.data;
  const agents = data?.system.agents;
  const disabled = data?.companies.filter((c) => c.disabled).length ?? 0;

  return (
    <main>
      <Hero tone="admin" eyebrow="Platform" title="Admin console" lede={LEDE} testId="admin-hero"
            actions={<PricingSwitch priced={priced} base="/admin" />} />
      {live.problem && <ApiProblem problem={live.problem} />}
      {data && (
        <>
          <LimitWarnings warnings={data.warnings} month={data.month} priced={priced} />
          <nav className="counters" aria-label="The platform at a glance" data-testid="admin-counters">
            <Link className="counter" href={`/admin/companies?priced_as=${priced}`} prefetch={false} data-testid="admin-count-companies">
              <span className="counter-label">Companies</span><span className="counter-value">{data.companies.length}</span>
              <span className="counter-sub">{disabled ? `${disabled} disabled` : "all enabled"}</span>
            </Link>
            <Link className="counter" href="/admin/people" prefetch={false}>
              <span className="counter-label">People</span>
              <span className="counter-value">{data.companies.reduce((n, c) => n + c.people, 0)}</span>
              <span className="counter-sub">across every company</span>
            </Link>
            <Link className="counter" href={`/admin/companies?priced_as=${priced}`} prefetch={false}>
              <span className="counter-label">Projects</span>
              <span className="counter-value">{data.companies.reduce((n, c) => n + c.projects, 0)}</span>
              <span className="counter-sub">{data.companies.reduce((n, c) => n + c.archived, 0)} archived</span>
            </Link>
            <Link className="counter" href="/admin/system" prefetch={false}>
              <span className="counter-label">Agents</span>
              <span className="counter-value fs-18">{agents?.enabled ? "on" : "off"}</span>
              <span className="counter-sub">{agents?.enabled ? `${agents.provider} · ${agents.model}` : (agents?.problem ?? "agents are off")}</span>
            </Link>
          </nav>
          <Panel title="What every company's agents used">
            <UsageKpis usage={data.total} />
            <p className="muted mt-10 mb-0">
              Costs are estimates: each run&apos;s recorded tokens priced at the chosen Claude model&apos;s list prices
              with its conversations cached. The tokens are those of the model that ran the agents.{" "}
              <Link href={`/admin/companies?priced_as=${priced}`}>Each company</Link> · <Link href={`/admin/usage?priced_as=${priced}`}>by agent, person, project or day</Link>
            </p>
          </Panel>
          <Panel title="The platform">
            <dl className="facts" data-testid="admin-system">
              <dt>Deployment</dt><dd>{data.system.deployment}</dd>
              <dt>Agents</dt>
              <dd>{agents?.enabled ? `${agents.provider} · ${agents.model}` : (agents?.problem ?? "agents are off")}</dd>
              <dt>Engine and keys</dt><dd><Link href="/admin/system">System status</Link></dd>
            </dl>
          </Panel>
        </>
      )}
    </main>
  );
}
