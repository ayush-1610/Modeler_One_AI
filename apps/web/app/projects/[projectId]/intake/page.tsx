import { Card } from "@/components/ui";

const RAW = [
  ["time_hr", "conc_ng_ml", "sd", "dose", "route"],
  ["0.5", "24.0", "3.1", "400", "po"],
  ["1.0", "40.0", "5.2", "400", "po"],
  ["2.0", "34.0", "4.4", "400", "po"],
  ["4.0", "19.0", "2.6", "400", "po"],
  ["8.0", "6.6", "1.1", "400", "po"],
  ["24.0", "0.4", "0.1", "400", "po"],
];

const MAPPING = [
  { column: "time_hr", target: "Time", unit: "h", ok: true },
  { column: "conc_ng_ml", target: "Concentration (mass)", unit: "ng/ml", ok: true },
  { column: "sd", target: "Arithmetic std. dev.", unit: "ng/ml", ok: true },
  { column: "dose", target: "Dose (protocol)", unit: "mg", ok: true },
  { column: "route", target: "Route (protocol)", unit: "—", ok: true },
];

export default async function IntakePage({ params }: { params: Promise<{ projectId: string }> }) {
  await params;
  return (
    <main>
      <h1>Data intake</h1>
      <p className="muted">Map each column of the uploaded observed-data sheet to an OSP dimension. The mapping is
        confirmed before the data enters the model; nothing is inferred silently.</p>

      <div className="cols-2 cols-intake">
        <Card title="Uploaded sheet — Example-A oral 400 mg (fasted)">
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead><tr>{RAW[0].map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>
                {RAW.slice(1).map((r, i) => (
                  <tr key={i}>{r.map((c, j) => <td key={j} className="num">{c}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Column mapping" action={<span className="chip low">all mapped</span>}>
          <table>
            <thead><tr><th>Column</th><th>OSP target</th><th>Unit</th></tr></thead>
            <tbody>
              {MAPPING.map((m) => (
                <tr key={m.column}>
                  <td><code>{m.column}</code></td>
                  <td>{m.target}</td>
                  <td>{m.unit}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="banner ok" style={{ marginTop: 14 }}>
            LLOQ 0.1 ng/ml detected and stored on the value column. Ready to confirm.
          </div>
          <div className="row" style={{ marginTop: 14 }}>
            <button className="btn primary">Confirm mapping</button>
            <button className="btn">Flag a question</button>
          </div>
        </Card>
      </div>
    </main>
  );
}
