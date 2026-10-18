import { redirect } from "next/navigation";

/** The brief and the data plan are part of Start since R2b (redesign §3.1): an old link lands there. */
export default async function BriefPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  redirect(`/projects/${projectId}/start`);
}
