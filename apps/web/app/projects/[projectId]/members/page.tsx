import { ApiProblem, Hero } from "@/components/kit";
import { MembersPanel } from "@/components/members/MembersPanel";
import { ProjectNotices } from "@/components/project/ProjectNotices";
import { getArchived, getMembers, getProject } from "@/lib/reads";

// A project's members (P-22, the console redesign's slice 3; before, a panel on the Run page): who may open it, its
// owner, and adding or removing a person with a reason (the owner only).
export default async function ProjectMembers({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [live, liveMembers, archived] = await Promise.all([getProject(projectId), getMembers(projectId), getArchived(projectId)]);
  return (
    <main>
      <Hero title="Members" lede="Who may open this project, and its owner, the one who changes it." />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && <ProjectNotices project={live.data} members={liveMembers.data} archived={archived} />}
      {live.data && <MembersPanel projectId={projectId} />}
    </main>
  );
}
