import { ModelInputs } from "@/components/inputs/ModelInputs";
import { Stepper } from "@/components/kit/Stepper";

/** P4 · Model inputs — the PK-Sim input pages. */
export default async function InputsPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <h1>Model inputs</h1>
      <Stepper projectId={projectId} current="inputs" page="inputs" />
      <p className="muted" style={{ maxWidth: "var(--measure)" }}>
        CPF v1 is assembled from the evidence, never typed, after every change: every value not excluded counts, each in its
        PK-Sim unit, with the source that goes into PK-Sim&apos;s value origin. The studies come from the datasets not
        excluded. Choices the evidence does not
        decide (which PK-Sim process carries a pathway, which formulation a tablet study used) are yours, with a reason.
        Readiness is the S0 check plus a build of every planned simulation.
      </p>
      <ModelInputs projectId={projectId} />
    </main>
  );
}
