import { PageShell } from "@/components/kit";
import { LibraryTable } from "@/components/library/LibraryTable";

/** The project document library (docs/plans/2026-10-28-project-document-library.md, PRs 1 and 2). */
export default async function LibraryPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <PageShell title="Project Document Library"
                 lede={<>Every document of this project: who added it, what it relates to, and what the project took from it.
                   A value&apos;s source is named where the value is used; this is where each document is listed once. Files are
                   added with “+ Add data” in the sidebar, and withdrawn here with a reason, never deleted.</>}>
        <LibraryTable projectId={projectId} />
      </PageShell>
    </main>
  );
}
