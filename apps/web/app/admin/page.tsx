import Link from "next/link";

import { AdminTabs, LimitWarnings, NotForYou, USAGE_HEADS, UsageCells, UsageKpis } from "@/components/admin/AdminParts";
import { Hero } from "@/components/kit";
import { ApiProblem, Card } from "@/components/ui";
import { getOverview, pricedAs, refused } from "@/lib/admin";

const LEDE = "Every company on the platform, its people, its projects and what its agents used. Read-only: each look is " +
  "recorded on the audit trail.";

/** The platform owner's console, its overview (docs/plans/2026-11-10-admin-console.md, build A). */
export default async function AdminPage({ searchParams }: { searchParams: Promise<{ priced_as?: string }> }) {
  const priced = pricedAs((await searchParams).priced_as);
  const live = await getOverview(priced);
  const data = live.data;
  const agents = data?.system.agents;

  return (
    <main>
      <Hero tone="admin" eyebrow="Platform" title="Admin console" lede={LEDE} testId="admin-hero" />
      {refused(live.problem) ? <NotForYou /> : (
        <>
          <AdminTabs here="overview" priced={priced} base="/admin" />
          {live.problem && <ApiProblem problem={live.problem} />}
          {data && (
            <>
              <LimitWarnings warnings={data.warnings} month={data.month} priced={priced} />
              <Card title="All companies">
                <UsageKpis usage={data.total} />
              </Card>
              <Card title="Companies">
                <div className="table-scroll">
                  <table data-testid="admin-companies">
                    <thead>
                      <tr><th>Company</th><th className="num">People</th><th className="num">Projects</th>
                        <th className="num">Archived</th>{USAGE_HEADS}</tr>
                    </thead>
                    <tbody>
                      {data.companies.map((c) => (
                        <tr key={c.tenant_id}>
                          <td><Link href={`/admin/companies/${encodeURIComponent(c.tenant_id)}?priced_as=${priced}`}>{c.tenant_id}</Link></td>
                          <td className="num">{c.people}</td>
                          <td className="num">{c.projects}</td>
                          <td className="num">{c.archived || "—"}</td>
                          <UsageCells usage={c.usage} />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
              <Card title="The platform">
                <dl className="facts" data-testid="admin-system">
                  <dt>Deployment</dt><dd>{data.system.deployment}</dd>
                  <dt>Agents</dt>
                  <dd>{agents?.enabled ? `${agents.provider} · ${agents.model}` : (agents?.problem ?? "agents are off")}</dd>
                </dl>
                <p className="muted" style={{ marginTop: 10 }}>
                  Costs are estimates: each run&apos;s recorded tokens priced at the chosen Claude model&apos;s list prices
                  with its conversations cached. The tokens are those of the model that ran the agents.
                </p>
              </Card>
            </>
          )}
        </>
      )}
    </main>
  );
}
