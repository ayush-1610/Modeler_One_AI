"use client";

// The project's model system (multi-compound phase 3, MS-01 v1.3 §6.5): its compounds and roles, how metabolites are
// formed, what each product doses, and where each analyte is judged. The dose fractions are entered per product and
// never defaulted (owner decision 2): a wrong salt correction or enantiomer split biases every exposure silently.

import { useState } from "react";

import { ApiProblem, Card } from "@/components/ui";
import { send, type Schema } from "@/lib/api";
import { useMutation, useResource } from "@/lib/hooks";

type SystemDetail = Schema<"SystemDetail">;
type Fractions = Record<string, Record<string, string>>;

function asText(products: SystemDetail["products"]): Fractions {
  return Object.fromEntries(Object.entries(products).map(([p, doses]) => [
    p, Object.fromEntries(Object.entries(doses).map(([c, f]) => [c, String(f)])),
  ]));
}

/** The entered fractions as numbers, or the first one that is not a fraction above zero. */
function parsed(draft: Fractions): { products: Record<string, Record<string, number>> | null; problem: string | null } {
  const products: Record<string, Record<string, number>> = {};
  for (const [product, doses] of Object.entries(draft)) {
    products[product] = {};
    for (const [compound, text] of Object.entries(doses)) {
      const value = Number(text);
      if (text.trim() === "" || !Number.isFinite(value) || value <= 0) {
        return { products: null, problem: `${product}: enter the dose fraction of ${compound} (above 0; never defaulted)` };
      }
      products[product][compound] = value;
    }
  }
  return { products, problem: null };
}

export function SystemPanel({ projectId }: { projectId: string }) {
  const { data, problem } = useResource("/api/v1/projects/{project_id}/system", { project_id: projectId });
  const { run, busy } = useMutation();
  const [draft, setDraft] = useState<Fractions | null>(null);
  const [outcome, setOutcome] = useState<{ ok: boolean; message: string } | null>(null);

  if (problem) return <Card title="Model system"><ApiProblem problem={problem} /></Card>;
  const system = data?.system;
  if (!data || !system || !data.links) return null;  // a single compound: no system to show
  const fractions = draft ?? asText(system.products);

  async function save() {
    const { products, problem: invalid } = parsed(fractions);
    if (!products) {
      setOutcome({ ok: false, message: invalid! });
      return;
    }
    const result = await run(() => send("put", "/api/v1/projects/{project_id}/system", { project_id: projectId },
                                        { ...data!.links, products }));
    setOutcome(result.problem ? { ok: false, message: result.problem } : { ok: true, message: "Dose fractions saved." });
    if (!result.problem) setDraft(null);
  }

  return (
    <Card title="Model system" action={<span className="muted">MS-01 v1.3 · {system.compounds.length} compounds</span>}>
      <div data-testid="system-panel">
        {system.problem && <div className="banner err" style={{ marginBottom: 12 }}>{system.problem}</div>}
        <table>
          <thead><tr><th>Compound</th><th>Role</th><th>CPF</th></tr></thead>
          <tbody>
            {system.compounds.map((c) => (
              <tr key={c.compound} data-testid={`system-compound-${c.compound}`}>
                <td>{c.compound}{c.compound === system.fitted && <span className="muted"> · fitted parent</span>}</td>
                <td>{c.role}</td>
                <td>{c.has_cpf ? "yes" : <span className="chip high">missing</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {system.formation.length > 0 && (
          <>
            <h3>Formation</h3>
            <table>
              <thead><tr><th>Formed</th><th>From</th><th>Process</th><th>Source</th></tr></thead>
              <tbody>
                {system.formation.map((f) => (
                  <tr key={`${f.compound}-${f.metabolite}-${f.process}`}>
                    <td>{f.metabolite}</td><td>{f.compound}</td><td><code>{f.process}</code></td><td className="muted">{f.data_source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}

        <h3>Products and dose fractions</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          The fraction of a product&apos;s reported dose each compound receives (salt correction × enantiomer share).
          Required for every dosed compound; never defaulted.
        </p>
        <table>
          <thead><tr><th>Product</th><th>Compound</th><th className="num">Dose fraction</th></tr></thead>
          <tbody>
            {Object.entries(fractions).flatMap(([product, doses]) => Object.entries(doses).map(([compound, text]) => (
              <tr key={`${product}-${compound}`}>
                <td>{product}</td>
                <td>{compound}</td>
                <td className="num">
                  <input aria-label={`Dose fraction of ${compound} in ${product}`} value={text} inputMode="decimal"
                         style={{ width: 110, textAlign: "right" }}
                         onChange={(e) => setDraft({ ...fractions, [product]: { ...fractions[product], [compound]: e.target.value } })} />
                </td>
              </tr>
            )))}
          </tbody>
        </table>
        <div className="spread" style={{ marginTop: 10 }}>
          <span className={outcome?.ok ? "muted" : ""} data-testid="system-outcome">
            {outcome && (outcome.ok ? outcome.message : <span className="chip high">{outcome.message}</span>)}
          </span>
          <button className="btn" disabled={busy || draft === null} onClick={save}>{busy ? "Saving…" : "Save dose fractions"}</button>
        </div>

        <h3>Analytes</h3>
        <table>
          <thead><tr><th>Analyte</th><th>Informs</th><th>Judged at</th></tr></thead>
          <tbody>
            {system.analytes.map((a) => (
              <tr key={a.name} data-testid={`system-analyte-${a.name}`}>
                <td>{a.name}<span className="muted"> · {a.kind}</span></td>
                <td>{a.informs.join(", ") || "—"}</td>
                <td>{a.judged_at.join(" · ") || <span className="muted">{a.note || "not judged"}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
