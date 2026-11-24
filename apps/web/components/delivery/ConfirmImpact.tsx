"use client";

// What confirming a changed card again would change (the console redesign's slice 4c): read before the signature from
// `/impact`, which plans the landing as the confirmation does and writes nothing. It names what would be loaded new,
// revised or set aside, and which artifacts of the project would go stale; a signed one (the MAP) must then be signed
// again on Review & sign. Read fresh each time the dialog opens: a value corrected a moment ago changes it.

import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import type { Schema } from "@/lib/api";
import { useResource } from "@/lib/hooks";

import { plural, type Subject } from "./shared";

type Impact = Schema<"DeliveryImpact">;
type Change = Impact["datasets"][number];

const IMPACT = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}/impact" as const;

// each artifact as the pages name it
const ARTIFACT: Record<string, string> = {
  brief: "The brief", requirements: "The data checklist", feasibility: "The feasibility check", evidence: "A value",
  dataset: "A dataset", client_submission: "A client file", dissolution: "A dissolution profile", cpf: "The compound's parameters (CPF)",
  study_catalog: "The study catalog", readiness: "The readiness check", model_plan: "The model plan", map: "The Model Analysis Plan (MAP)",
  campaign: "A campaign",
};
const CHANGE_WORD: Record<Change["change"], string> = {
  new: "loaded new", revised: "revised (a new version)", accepted: "accepted", unchanged: "unchanged", held: "held back",
  set_aside: "set aside (rejected)",
};
const ORDER: Change["change"][] = ["new", "revised", "accepted", "set_aside", "held"];

function counted(rows: Change[], what: string, many: string) {
  return ORDER.map((c) => [c, rows.filter((r) => r.change === c).length] as const).filter(([, n]) => n > 0)
    .map(([c, n]) => `${plural(n, what, many)} ${CHANGE_WORD[c]}`).join(", ");
}

export function ConfirmImpact({ projectId, subject }: { projectId: string; subject: Subject }) {
  const client = useQueryClient();
  const params = { project_id: projectId, type: subject.subject_type, subject: subject.subject };
  const read = useResource(IMPACT, params);
  // the answer is put away when the dialog closes, so the next one reads what the card holds then (no change marks it)
  const key = JSON.stringify(params);
  useEffect(() => () => client.removeQueries({ queryKey: [IMPACT, JSON.parse(key), {}], exact: true }), [client, key]);
  const impact: Impact | null = read.data;
  return (
    <section className="delivery-impact" aria-labelledby="impact-title" data-testid="delivery-confirm-impact">
      <h3 id="impact-title">What signing again changes</h3>
      {read.problem ? <p className="muted m-0" data-testid="delivery-impact-problem">What it would change could not be read
            ({read.problem}). The record above is still what you sign.</p>
        : !impact ? <p className="muted m-0">Reading what it would change…</p>
        : !impact.changes ? <p className="m-0" data-testid="delivery-impact-none">Nothing the model reads changes: the same datasets
            and values are loaded again.</p>
        : <ImpactBody impact={impact} />}
    </section>
  );
}

function ImpactBody({ impact }: { impact: Impact }) {
  const moved = (rows: Change[]) => rows.filter((r) => r.change !== "unchanged");
  const datasets = moved(impact.datasets);
  const values = moved(impact.evidence);
  const resign = impact.affected.filter((a) => a.needs_signature);
  return (
    <>
      <ul className="plain-list" data-testid="delivery-impact-loads">
        {datasets.length > 0 && (
          <li data-testid="delivery-impact-datasets">Datasets: {counted(datasets, "dataset", "datasets")}
            <ul className="plain-list muted fs-12">{datasets.map((d) => <li key={d.id}>{d.label}: {CHANGE_WORD[d.change]}</li>)}</ul>
          </li>
        )}
        {values.length > 0 && <li data-testid="delivery-impact-values">Values: {counted(values, "value", "values")}</li>}
        {(impact.dissolution_rows > 0 || impact.dissolution_removed > 0) && (
          <li data-testid="delivery-impact-dissolution">Dissolution: {plural(impact.dissolution_rows, "row")} loaded
            {impact.dissolution_removed > 0 ? `, ${plural(impact.dissolution_removed, "row")} the earlier confirmation loaded removed` : ""}</li>
        )}
        {impact.reject_legacy.length > 0 && (
          <li>Rejected as replaced: {plural(impact.reject_legacy.length, "dataset")} read earlier with the sheet form</li>
        )}
      </ul>
      {resign.length > 0 && (
        <div className="delivery-blocked warn" role="note" data-testid="delivery-impact-resign">
          <strong>Signed work goes stale:</strong>
          <ul className="plain-list">
            {resign.map((a) => <li key={`${a.ref.kind}-${a.ref.id}`}>{ARTIFACT[a.ref.kind] ?? a.ref.kind}, version {a.ref.version}: it must
              be signed again{a.ref.kind === "map" ? " on Review & sign, and campaigns bound to it are invalidated" : ""}.</li>)}
          </ul>
        </div>
      )}
      {impact.affected.length > 0 && (
        <details className="delivery-impact-affected" data-testid="delivery-impact-affected">
          <summary>Then {plural(impact.affected.length, "project record")} change{impact.affected.length === 1 ? "s" : ""}</summary>
          <ul className="plain-list fs-12">
            {impact.affected.map((a) => (
              <li key={`${a.ref.kind}-${a.ref.id}`}>{ARTIFACT[a.ref.kind] ?? a.ref.kind}, version {a.ref.version}: <span className="muted">{a.effect}</span></li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
