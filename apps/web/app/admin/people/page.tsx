import { People } from "@/components/admin/People";
import { ApiProblem, Hero } from "@/components/kit";
import { getPeople, hideUnlessAdmin } from "@/lib/admin";

const LEDE = "Every person of every company, as Keycloak keeps them: add them, give or take roles, move, disable, reset a " +
  "lost authenticator or password. Passwords are never typed here.";

/** The realm's people (docs/plans/2026-11-10-admin-console.md, F). */
export default async function PeoplePage() {
  const live = await getPeople();
  hideUnlessAdmin(live.problem);
  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="People" lede={LEDE} />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && <People initial={live.data} />}
    </main>
  );
}
