import { AdminTabs, LimitWarnings } from "@/components/admin/AdminParts";
import { Limits } from "@/components/admin/Limits";
import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { getLimits, hideUnlessAdmin, pricedAs } from "@/lib/admin";

const LEDE = "A monthly spend and token limit per company, project or person. You are warned at 80 % and when a limit is " +
  "reached; the agents keep running, and the companies' people see nothing of it.";

/** The monthly limits (docs/plans/2026-11-10-admin-console.md, E; the owner's answer 2). */
export default async function LimitsPage({ searchParams }: { searchParams: Promise<{ priced_as?: string }> }) {
  const priced = pricedAs((await searchParams).priced_as);
  const live = await getLimits(priced);
  hideUnlessAdmin(live.problem);
  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="Limits" lede={LEDE} />
      <AdminTabs here="limits" priced={priced} base="/admin/limits" />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && (
        <>
          <LimitWarnings warnings={live.data.warnings} month={live.data.month} priced={priced} />
          <Limits initial={live.data} priced={priced} />
        </>
      )}
    </main>
  );
}
