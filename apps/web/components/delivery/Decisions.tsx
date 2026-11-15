"use client";

// The decisions made on a subject, listed before "Confirm and sign" (plan 2026-11-14 §2.2.4): the signer sees what was
// accepted as is, entered or corrected, settled as a required item, not used, refused as a link, which of its tables'
// layouts were approved or rejected and which of its files' tables were marked as not data, each with who decided it,
// when and why. What each decision is comes from the card and the delivery page; who, when and why from the project's
// audit trail (a table marked as not data says it itself) (its last 2,000 events, read only while the list is on screen). A decision the trail does not name a
// person for (a value not used after a choice, a refused link) is listed with its reason only. Values linked to the
// study from a file that did not name it are decided per file, in Client files: the trail does not say which study a
// link went to, so they are not listed here (an API follow-up: a subject's decisions on its card).

import { useResource } from "@/lib/hooks";
import { engineWords, fieldLabel, placeText, tableKindText, valueWord, whenText, DISPOSITION_WORD } from "@/lib/words";

import { plural, valueText, type Subject, type Value } from "./shared";

type Event = { action: string; actor: string; occurred_at: string; reason: string | null; resource_id: string; after: unknown };
type Line = { id: string; what: string; by?: string; at?: string; why?: string };

const AUDIT_EVENTS = "2000";
const last = (resource: string) => resource.slice(resource.lastIndexOf("/") + 1);
const after = (e: Event) => (e.after && typeof e.after === "object" ? e.after as Record<string, unknown> : {});

/** Who decided what on `subject`, newest first. `files` are the subject's files (their tables marked as not data). */
export function Decisions({ projectId, subject, files: shas }: { projectId: string; subject: Subject; files: string[] }) {
  const delivery = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId });
  const values = subject.tables.flatMap((t) => t.values);
  const overridden = subject.checks.filter((c) => c.overridden);
  const disposed = subject.requirements.filter((r) => DISPOSITION_WORD[r.status] && r.disposition);
  const entered = values.filter((v) => v.method === "person");
  const unused = values.filter((v) => v.status === "excluded" && v.status_reason);
  const refused = subject.links.filter((l) => l.state === "refused");
  const layouts = new Map<string, { id: string; version: number; kind: string | null; file: string | null; status: string }>();
  for (const t of subject.tables) {
    if (t.mapping_id && t.mapping_version !== null && (t.mapping_status === "approved" || t.mapping_status === "rejected")) {
      layouts.set(`${t.mapping_id}/${t.mapping_version}`, { id: t.mapping_id, version: t.mapping_version, kind: t.table_kind, file: t.file,
                                                            status: t.mapping_status });
    }
  }
  const files = (delivery.data?.enabled ? delivery.data.deliveries.flatMap((d) => d.files) : [])
    .filter((f) => shas.includes(f.sha256) && !f.repeat);
  // a table marked as not data says who decided it, when and why itself (`DeliveryRegion.decision`)
  const notData = files.flatMap((f) => f.regions.map((r) => ({ f, r, d: r.decision }))).filter((x) => x.d);
  const count = overridden.length + disposed.length + entered.length + unused.length + refused.length + layouts.size + notData.length;
  const trail = useResource("/api/v1/projects/{project_id}/audit", { project_id: projectId },
                            { query: { limit: AUDIT_EVENTS }, enabled: count > 0 });
  const events = (trail.data?.events ?? []) as Event[];
  const find = (action: string, match: (e: Event) => boolean) => events.find((e) => e.action === action && match(e));
  const said = (e: Event | undefined) => (e ? { by: e.actor, at: e.occurred_at, why: e.reason ?? undefined } : {});
  const name = (v: Value) => `${fieldLabel(v.field)}${v.time !== null ? ` at ${v.time}${v.time_unit ? ` ${v.time_unit}` : ""}` : ""}`;

  const decided: Line[] = [
    ...overridden.map((c) => ({ id: `ov-${c.id}`, what: `Accepted as is: ${engineWords(c.message ?? "a check")}`,
                                ...said(find("intake.override", (e) => after(e).check_id === c.id)) })),
    ...disposed.map((r) => ({ id: `dp-${r.req_id}`, what: `${r.label}: ${DISPOSITION_WORD[r.status]}`,
                              ...said(find("intake.disposition", (e) => after(e).disposition === r.disposition)) })),
    ...entered.map((v) => ({ id: `en-${v.id}`, what: `${v.blinded ? "Entered" : `Entered ${typeof v.value === "string" ? valueWord(v.value) : valueText(v)}${v.unit ? ` ${v.unit}` : ""}`} for ${name(v)}`,
                             ...said(find("intake.entry", (e) => last(e.resource_id) === v.id)) })),
    ...unused.map((v) => ({ id: `ex-${v.id}`, what: `Not used: ${name(v)} from ${v.file ?? "a person's entry"}`, why: v.status_reason })),
    ...refused.map((l) => ({ id: `lk-${l.id}`, what: `${l.file} is not about this study` })),
    ...[...layouts.values()].map((m) => ({
      id: `mp-${m.id}-${m.version}`, what: `Table layout ${m.status}: the ${tableKindText(m.kind)} of ${m.file ?? "a file"}, version ${m.version}`,
      ...said(find(`intake.mapping.${m.status === "approved" ? "approve" : "reject"}`,
                   (e) => after(e).mapping_id === m.id && after(e).version === m.version)),
    })),
    ...notData.map(({ f, r, d }) => ({ id: `rd-${d!.id}-${r.region_id}`, what: `Marked as not data: ${placeText(r.where)} of ${f.name}`,
                                       by: d!.by, at: d!.at, why: d!.why })),
  ];
  const lines = [...decided].sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));

  return (
    <section className="delivery-block card-section" data-testid={`delivery-decisions-${subject.subject}`}>
      <div className="delivery-block-head">
        <h3>Decisions made on this {subject.subject_type === "compound" ? "compound" : subject.subject_type}</h3>
        <span className="muted fs-13">{count ? plural(count, "decision") : "none yet"}</span>
      </div>
      {count === 0 ? <p className="muted m-0">No one has decided anything on it yet: what your signature binds is what its files say.</p> : (
        <>
          <p className="muted m-0 fs-13">Your signature binds these too. Each was made with its reason, kept on the audit trail.</p>
          <ul className="decision-list">
            {lines.map((l) => (
              <li key={l.id} data-testid={`decision-${l.id}`}>
                <span className="decision-what">{l.what}</span>
                <span className="muted fs-12">{[l.by ? `${l.by}${l.at ? `, ${whenText(l.at)}` : ""}` : "", l.why ? `“${l.why}”` : ""].filter(Boolean).join(" · ")}</span>
              </li>
            ))}
          </ul>
          {trail.problem && <p className="muted fs-12 m-0">Who made each decision could not be read from the audit trail: {trail.problem}</p>}
        </>
      )}
    </section>
  );
}
