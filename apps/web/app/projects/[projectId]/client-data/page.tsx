import { ClientData } from "@/components/client/ClientData";
import { Stepper } from "@/components/kit/Stepper";

/** P3 · Client data — review layer L2b. */
export default async function ClientDataPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <h1>Client data</h1>
      <Stepper projectId={projectId} current="inputs" page="client-data" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        <strong>Review layer 2b.</strong> Upload what the client sent, read each data sheet with the guided form (nothing is
        guessed: every unit, dose and LLOQ points back to its cell), and settle what the data plan still expects. Approval
        closes the phase.
      </p>
      <ClientData projectId={projectId} />
    </main>
  );
}
