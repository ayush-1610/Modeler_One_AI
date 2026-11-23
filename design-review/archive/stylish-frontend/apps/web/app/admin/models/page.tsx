import { AdminTabs } from "@/components/admin/AdminParts";
import { AgentModels } from "@/components/admin/AgentModels";
import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { getAgents, hideUnlessAdmin } from "@/lib/admin";

/** Each agent's model, chosen in the console (docs/plans/2026-11-10-admin-console.md, C). */
export default async function ModelsPage() {
  const live = await getAgents();
  hideUnlessAdmin(live.problem);
  return (
    <main>
      <Hero tone="admin" eyebrow="Admin console" title="Models"
            lede="Which model each agent runs on. A change takes effect at the agent's next run, with its reason kept." />
      <AdminTabs here="models" />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && <AgentModels initial={live.data} />}
    </main>
  );
}
