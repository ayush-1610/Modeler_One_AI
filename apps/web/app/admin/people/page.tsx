import { AdminTabs } from "@/components/admin/AdminParts";
import { People } from "@/components/admin/People";
import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { getPeople, hideUnlessAdmin } from "@/lib/admin";

const LEDE = "Every person of every company, as Keycloak keeps them: add them, give or take roles, move, disable, reset a " +
  "lost authenticator. Passwords are never typed here.";

/** The realm's people (docs/plans/2026-11-10-admin-console.md, F). */
export default async function PeoplePage() {
  const live = await getPeople();
  hideUnlessAdmin(live.problem);
  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="People" lede={LEDE} />
      <AdminTabs here="people" />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && <People initial={live.data} />}
    </main>
  );
}
