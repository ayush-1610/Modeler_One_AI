import Link from "next/link";

import type { Schema } from "@/lib/api";
import type { Project } from "@/lib/types";

// What a person must know before they act on a project's page (the console redesign's slice 3; PRODUCT_SITEMAP.md
// "Read-only state"): that it is archived, or that it is shared with them to read and who changes it. From the API's own
// answers (the project list's `archived`, `GET /projects/{id}/members`); the API enforces both whatever the page shows.
export function ProjectNotices({ project, members, archived }: {
  project: Project; members: Schema<"MembersPage"> | null; archived: Project["archived"];
}) {
  const base = `/projects/${encodeURIComponent(project.id)}`;
  return (
    <>
      {archived && (
        <div className="banner warn mb-16" role="status" data-testid="project-archived-notice">
          <strong>Archived</strong> by {archived.by} on {archived.at.slice(0, 10)}: {archived.reason}.
          {" "}Nothing it holds was changed or erased. <Link href={`${base}/settings`}>Restore it in Settings</Link>.
        </div>
      )}
      {members && members.managed && !members.you_change_it && (
        <div className="banner info mb-16" role="status" data-testid="read-only-notice">
          Shared with you to read. Only the owner, <strong>{members.owner_name ?? members.owner}</strong>, changes it
          {" "}(a reviewer it is shared with still signs its plan and decides its escalations).
        </div>
      )}
    </>
  );
}
