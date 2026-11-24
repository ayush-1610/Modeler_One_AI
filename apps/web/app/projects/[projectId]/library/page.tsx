import { PageShell } from "@/components/kit";
import { AddDocuments } from "@/components/library/AddDocuments";
import { LibraryTable } from "@/components/library/LibraryTable";

/** Documents (P-18; the project document library, docs/plans/2026-10-28-project-document-library.md; the console
 *  redesign's slice 7): every document of this project, who added it, what it relates to and what the project took
 *  from it; a document opens beside the list. */
export default async function LibraryPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <PageShell tone="library" eyebrow="Project record" title="Documents" slim
                 lede={<>Every document of this project: who added it, what it relates to, and what the project took from it. A
                   value&apos;s source is named where the value is used; each document is listed here once. A document is
                   withdrawn with a reason, never deleted.</>}
                 actions={<AddDocuments projectId={projectId} />}>
        <LibraryTable projectId={projectId} />
      </PageShell>
    </main>
  );
}
