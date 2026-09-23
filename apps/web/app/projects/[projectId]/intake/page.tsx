import { DataIntake } from "@/components/DataIntake";

export default async function IntakePage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return (
    <main>
      <h1>Data intake</h1>
      <p className="muted">Upload an observed clinical concentration-time profile and map each column to its
        meaning. The mapping is confirmed before the data enters the model; nothing is inferred silently.</p>
      <DataIntake projectId={projectId} />
    </main>
  );
}
