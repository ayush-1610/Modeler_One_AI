import Link from "next/link";
import { notFound } from "next/navigation";

import { AdminTabs, USAGE_HEADS, UsageCells, UsageKpis } from "@/components/admin/AdminParts";
import { GiveProjects } from "@/components/admin/GiveProjects";
import { Hero } from "@/components/kit";
import { ApiProblem, Card } from "@/components/ui";
import { getCompany, pricedAs, refused } from "@/lib/admin";

/** One company in full: its people and projects, each with what its agents used (the console, build A). */
export default async function CompanyPage({ params, searchParams }: {
  params: Promise<{ tenantId: string }>; searchParams: Promise<{ priced_as?: string }>;
}) {
  const tenantId = decodeURIComponent((await params).tenantId);
  const priced = pricedAs((await searchParams).priced_as);
  const live = await getCompany(tenantId, priced);
  // An unknown company and a person without modeler-admin (the API's 403) look the same: the app's 404.
  if (live.notFound || refused(live.problem)) notFound();
  const data = live.data;
  const base = `/admin/companies/${encodeURIComponent(tenantId)}`;

  return (
    <main>
      <Hero tone="admin" eyebrow={<Link href={`/admin?priced_as=${priced}`}>Admin console</Link>} title={tenantId}
            lede="Its people (everyone who has signed in), its projects (archived ones too) and what their agents used." />
      <AdminTabs here="company" priced={priced} base={base} />
      {live.problem && <ApiProblem problem={live.problem} />}
      {data && (
        <>
          <Card title="This company"><UsageKpis usage={data.usage} /></Card>
          <Card title="People">
            <div className="table-scroll">
              <table data-testid="admin-people">
                <thead><tr><th>Name</th><th>Sign-in id</th><th>Projects</th>{USAGE_HEADS}</tr></thead>
                <tbody>
                  {data.people.map((p) => (
                    <tr key={p.subject}>
                      <td>{p.name}</td>
                      <td className="muted"><code>{p.subject}</code></td>
                      <td>{p.projects.length ? p.projects.join(", ") : "—"}</td>
                      <UsageCells usage={p.usage} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted mt-10">
              A person&apos;s runs are those their actions started, recorded from 10 November 2026.
            </p>
          </Card>
          <Card title="Projects">
            <div className="table-scroll">
              <table data-testid="admin-projects">
                <thead><tr><th>Project</th><th>Compounds</th><th>Members</th><th>State</th>{USAGE_HEADS}</tr></thead>
                <tbody>
                  {data.projects.map((p) => (
                    <tr key={p.id}>
                      <td>{p.name}<div className="muted"><code>{p.id}</code></div></td>
                      <td>{p.compounds.join(", ") || "—"}</td>
                      <td>{p.members.join(", ") || "—"}</td>
                      <td>{p.archived ? <>Archived<div className="muted">{p.archived_reason}</div></> : "Active"}</td>
                      <UsageCells usage={p.usage} />
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
          <GiveProjects tenantId={tenantId} people={data.people.map((p) => ({ subject: p.subject, name: p.name,
                                                                               projects: p.projects }))} />
          <p><Link href={`/admin/usage?tenant_id=${encodeURIComponent(tenantId)}&priced_as=${priced}`}>
            This company&apos;s runs, one by one →</Link></p>
        </>
      )}
    </main>
  );
}
