import { ClientData } from "@/components/client/ClientData";
import { PhaseRail } from "@/components/PhaseRail";

/** P3 · Client data — review layer L2b. */
export default async function ClientDataPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <h1>Client data</h1>
      <PhaseRail projectId={projectId} current="P3" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>Review layer 2b.</strong> What the client sent, read without guessing: the client-data template is read
        cell by cell; any other workbook is sorted sheet by sheet and read once you confirm how; reports and papers are
        kept as citable documents. Every value points back to its cell. The reconciliation shows, item by item, what the
        data plan expects from the client and what arrived. A missing item is skipped as not available or checked against
        the literature instead; then the phase closes with your approval.
      </p>
      <ClientData projectId={projectId} />
    </main>
  );
}
