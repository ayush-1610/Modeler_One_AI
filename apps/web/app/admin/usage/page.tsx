import { AdminTabs, NotForYou, UsageKpis, UsageTable } from "@/components/admin/AdminParts";
import { Hero } from "@/components/kit";
import { ApiProblem, Card } from "@/components/ui";
import { getUsage, pricedAs, refused, tokens, usd, when } from "@/lib/admin";

const LEDE = "What the agents used, per agent, project, person, company and day, and each run with who started it. " +
  "Costs are estimates at the chosen Claude model's list prices, with caching.";

/** The agents' usage and its cost (the console, build B). The filters are a plain form: the page is read on the server. */
export default async function UsagePage({ searchParams }: {
  searchParams: Promise<{ since?: string; tenant_id?: string; priced_as?: string }>;
}) {
  const query = await searchParams;
  const priced = pricedAs(query.priced_as);
  const since = query.since && /^\d{4}-\d{2}-\d{2}$/.test(query.since) ? query.since : undefined;
  const tenant = query.tenant_id || undefined;
  const live = await getUsage({ since, tenant_id: tenant, priced_as: priced });
  const data = live.data;

  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="Usage and cost" lede={LEDE} />
      {refused(live.problem) ? <NotForYou /> : (
        <>
          <AdminTabs here="usage" priced={priced} base="/admin/usage" query={{ since, tenant_id: tenant }} />
          {live.problem && <ApiProblem problem={live.problem} />}
          <Card>
            <form className="admin-filter" method="get" action="/admin/usage" data-testid="usage-filter">
              <label>Since<input type="date" name="since" defaultValue={since ?? ""} /></label>
              <label>Company<input type="text" name="tenant_id" defaultValue={tenant ?? ""} placeholder="every company" /></label>
              <input type="hidden" name="priced_as" value={priced} />
              <button type="submit" className="btn">Show</button>
            </form>
          </Card>
          {data && (
            <>
              <Card title={tenant ? `Company ${tenant}` : "Every company"}><UsageKpis usage={data.total} /></Card>
              <div className="admin-grid">
                <UsageTable title="By agent" column="Agent" rows={data.by_agent} testId="usage-by-agent" />
                <UsageTable title="By person" column="Person (company)" rows={data.by_person} testId="usage-by-person" />
                <UsageTable title="By project" column="Project (company)" rows={data.by_project} testId="usage-by-project" />
                <UsageTable title="By company" column="Company" rows={data.by_company} testId="usage-by-company" />
              </div>
              <UsageTable title="By day" column="Day" rows={data.by_day} testId="usage-by-day" />
              <Card title={`Runs (newest first${data.runs.length >= data.limit ? `, the first ${data.limit}` : ""})`}>
                {data.runs.length === 0 ? <p className="muted">No runs.</p> : (
                  <div className="table-scroll">
                    <table data-testid="usage-runs">
                      <thead>
                        <tr><th>Started</th><th>Agent</th><th>Company · project</th><th>Started by</th><th>Status</th>
                          <th className="num">Turns</th><th className="num">Input</th><th className="num">Output</th>
                          <th className="num">Est. cost</th></tr>
                      </thead>
                      <tbody>
                        {data.runs.map((r) => (
                          <tr key={r.run_id}>
                            <td>{when(r.started_at)}</td>
                            <td>{r.agent}<div className="muted">{r.model}</div></td>
                            <td>{r.tenant_id}{r.project_id ? ` · ${r.project_id}` : ""}</td>
                            <td>{r.started_by_name ?? r.started_by ?? <span className="muted">not recorded</span>}</td>
                            <td>{r.status}</td>
                            <td className="num">{r.turns}</td>
                            <td className="num">{tokens(r.input_tokens)}</td>
                            <td className="num">{tokens(r.output_tokens)}</td>
                            <td className="num">{usd(r.usd)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
              <p className="muted">
                Prices of {priced} per million tokens: input ${data.prices.input}, cache write ${data.prices.cache_write_5m},
                cache read ${data.prices.cache_read}, output ${data.prices.output}.
              </p>
            </>
          )}
        </>
      )}
    </main>
  );
}
