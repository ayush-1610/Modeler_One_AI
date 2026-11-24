// A project's settings (the redesign's P-23; the owner, 2026-11-24: the pages we are missing; the console redesign's
// slice 3): its owner, archive and restore with a reason, its blinding (shown here, set on Review & sign), and who it is
// shared with (managed on Members). Each part is the component its own page uses, so the rules (only the owner archives
// and changes members) hold here as there. Where the client's files may go for an AI model to read is not here: an
// administrator sets it for the whole company on Admin → Companies (the owner, 2026-11-24).

import Link from "next/link";

import { Hero } from "@/components/kit";
import { ArchiveControl } from "@/components/project/ArchiveControl";
import { ProjectNotices } from "@/components/project/ProjectNotices";
import { ApiProblem } from "@/components/ui";
import { getArchived, getBlinding, getMembers, getProject } from "@/lib/reads";

export const metadata = { title: "Project settings · Modeler One" };

export default async function ProjectSettings({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  const [live, liveMembers, liveBlinding, archived] = await Promise.all([getProject(projectId), getMembers(projectId), getBlinding(projectId), getArchived(projectId)]);
  const base = `/projects/${encodeURIComponent(projectId)}`;
  const members = liveMembers.data;
  const blinding = liveBlinding.data;
  return (
    <main data-testid="project-settings">
      <Hero title="Settings" lede="Its owner, whether it is archived, its blinding, and who it is shared with." />
      {live.problem && <ApiProblem problem={live.problem} />}
      {live.data && (
        <>
          <ProjectNotices project={live.data} members={members} archived={archived} />
          <section className="panel mb-16" aria-labelledby="settings-owner" data-testid="settings-owner">
            <div className="panel-head"><h2 id="settings-owner">Owner and archive</h2></div>
            <div className="panel-body">
              <p>Owned by <strong>{members?.owner_name ?? members?.owner ?? "no one on record (its members change it)"}</strong>. Only the owner changes the project.</p>
              <ArchiveControl projectId={projectId} name={live.data.name} archived={Boolean(archived)}
                              mayChange={members?.you_change_it ?? false} ownerName={members?.owner_name ?? null} />
            </div>
          </section>
          <section className="panel mb-16" aria-labelledby="settings-blinding" data-testid="settings-blinding">
            <div className="panel-head"><h2 id="settings-blinding">Blinding</h2><span className="grow" /><Link href={`${base}/plan`}>Set on Review &amp; sign</Link></div>
            <div className="panel-body">
              {liveBlinding.problem ? <p className="muted m-0">The blinding could not be read ({liveBlinding.problem}).</p> : blinding && (
                <p className="m-0">
                  <strong>{blinding.on ? "On" : "Off"}</strong>: {blinding.on
                    ? "external-validation studies are withheld until the MAP is signed"
                    : "external values are visible"}{blinding.reason ? ` (${blinding.reason})` : ""}.
                  {blinding.on && blinding.blinded.length > 0 && <> Withheld now: {blinding.blinded.join(", ")}.</>}
                </p>
              )}
            </div>
          </section>
          <section className="panel" aria-labelledby="settings-members" data-testid="settings-members">
            <div className="panel-head"><h2 id="settings-members">Shared with</h2><span className="grow" /><Link href={`${base}/members`} data-testid="settings-members-link">Members</Link></div>
            <div className="panel-body">
              <p className="m-0">{members ? `${members.members.length} member${members.members.length === 1 ? "" : "s"}: ${members.members.map((m) => m.name).join(", ")}.` : "The members could not be read."}</p>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
