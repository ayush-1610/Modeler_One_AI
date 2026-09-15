import type { QuestionStatus } from "@/lib/api";

// Example rows until the questions-of-interest endpoint exists.
const EXAMPLE_QUESTIONS: QuestionStatus[] = [
  {
    id: "qoi-1",
    question: "AUC ratio of Example-A with itraconazole 200 mg QD; label dose adjustment?",
    application: "DDI (CYP3A4)",
    modelRisk: "high",
    stage: "evaluation",
    failingCriteria: 1,
  },
  {
    id: "qoi-2",
    question: "Dose for children 2 to <6 years matching adult AUC",
    application: "Pediatric extrapolation",
    modelRisk: "medium",
    stage: "planning",
    failingCriteria: 0,
  },
];

export default function ProgramDashboard() {
  return (
    <main style={{ maxWidth: 1100, marginInline: "auto", paddingBlock: 32 }}>
      <h1>Example-A program</h1>
      <p>Example data. Each question of interest has its own ICH M15 assessment table.</p>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th align="left">Question of interest</th>
              <th align="left">Application</th>
              <th align="left">Model risk</th>
              <th align="left">Stage</th>
              <th align="right">Failing criteria</th>
            </tr>
          </thead>
          <tbody>
            {EXAMPLE_QUESTIONS.map((q) => (
              <tr key={q.id}>
                <td>{q.question}</td>
                <td>{q.application}</td>
                <td>{q.modelRisk ?? "not rated"}</td>
                <td>{q.stage}</td>
                <td align="right" style={{ fontVariantNumeric: "tabular-nums" }}>
                  {q.failingCriteria}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
