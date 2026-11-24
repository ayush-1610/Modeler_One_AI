// A project's settings (the redesign's P-23; the owner, 2026-11-24: the pages we are missing): who owns it and who it
// is shared with, and where its client files may go for an AI model to read. Each part is the component its own page
// already uses, so the rules (only the owner or an administrator changes the files' permission; only the owner changes
// members) hold here as there.

import { FilesGo } from "@/components/dataroom/FilesGo";
import { Hero } from "@/components/kit";
import { MembersPanel } from "@/components/members/MembersPanel";
import { ApiProblem } from "@/components/ui";
import { getProject } from "@/lib/reads";

export const metadata = { title: "Project settings · Modeler One" };

export default async function ProjectSettings({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const live = await getProject(projectId);
  return (
    <main data-testid="project-settings">
      <Hero tone="run" eyebrow="Project settings" title={live.data?.name ?? projectId}
            lede="Who owns this project and who it is shared with, and where its client files may go." />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && (
        <>
          <section className="card mb-16" aria-labelledby="settings-files">
            <h2 id="settings-files">Where the client&apos;s files may go</h2>
            <p className="muted">In-house only unless the client&apos;s written permission for a cloud service is recorded here.
              The AI agents follow it for every file of this project.</p>
            <FilesGo projectId={projectId} />
          </section>
          <MembersPanel projectId={projectId} />
          {live.data.archived && (
            <div className="banner warn mt-16" data-testid="settings-archived">
              Archived by {live.data.archived.by} on {live.data.archived.at.slice(0, 10)}: {live.data.archived.reason}. Restore it
              from the projects list.
            </div>
          )}
        </>
      )}
    </main>
  );
}
