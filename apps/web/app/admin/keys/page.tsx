import { AdminTabs, NotForYou } from "@/components/admin/AdminParts";
import { ProviderKeys } from "@/components/admin/ProviderKeys";
import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { getKeys, refused } from "@/lib/admin";

/** The providers' keys: stored sealed, shown by their last 4 characters, rotated here (the console, D). */
export default async function KeysPage() {
  const live = await getKeys();
  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="Keys"
            lede="The providers' keys, sealed under the server's master key. Add, test, make active, retire: no restart." />
      {refused(live.problem) ? <NotForYou /> : (
        <>
          <AdminTabs here="keys" />
          {live.problem && <ApiProblem problem={live.problem} />}
          {live.data && <ProviderKeys initial={live.data} />}
        </>
      )}
    </main>
  );
}
