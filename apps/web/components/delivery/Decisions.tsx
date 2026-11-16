"use client";

// The decisions a subject's signature binds, listed before "Confirm and sign" (plan 2026-11-14 §2.2.4; final review
// INT-1, INT-6, INT-8, gaps 6 and 9): each with who decided it, when and why. The card's API gives them
// (`DeliverySubject.decisions`, read from the intake's own logs, where each line holds who, when and why): the checks
// accepted as is (every one, not only the newest), the required items settled, the facts entered or corrected, the
// disagreements kept, the links between files, the values linked to the subject, the layouts of its tables (naming every
// file each one reads) and its files' tables and notes marked as not data or given back. The clean-up of the delivery's
// other files is bound by the signature too (the gate is per delivery, contracts §11.10): it is said in one line and
// listed in a fold. A blinded study's decisions come with the digits of their reasons masked and no value entered
// (D-15, the delivery's own rule): a withheld entry reads "Entered for Dose (value withheld)". `ChangedSince` names
// what changed after a confirmation was signed, from the same list.

import type { ReactNode } from "react";

import type { Schema } from "@/lib/api";
import { engineWords, layoutFieldInText, layoutFieldText, placeText, tableKindText, valueWord, whenText, DISPOSITION_WORD } from "@/lib/words";

import { num, plural, type Subject } from "./shared";

export type Decision = Schema<"DeliveryDecision">;

/** "A", "A and B", "A, B and C". */
const listed = (names: string[]) => (names.length < 2 ? names[0] ?? "" : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`);
const ROLE_WORD: Record<string, string> = { study: "study", arm: "arm", product: "product", batch: "batch", analyte: "analyte" };

function timeOf(d: Decision): string {
  return d.time !== null ? ` at ${num(d.time)}${d.time_unit ? ` ${d.time_unit}` : ""}` : "";
}

/** What a decision decided, in a person's words, on the card of `subject`. */
export function decisionText(d: Decision, subject: Subject): string {
  const kind = subject.subject_type === "compound" ? "compound" : subject.subject_type;
  const file = listed(d.files);
  switch (d.kind) {
    case "override": {
      const check = subject.checks.find((c) => c.id === d.check_id);
      return `Accepted as is: ${check?.message ? engineWords(check.message) : subject.blinded ? "a check (withheld, blinded)" : "a check"}`;
    }
    case "disposition": {
      const item = subject.requirements.find((r) => r.req_id === d.req_id);
      return `${item?.label ?? "A required item"}: ${DISPOSITION_WORD[d.disposition ?? ""] ?? valueWord(d.disposition ?? "settled")}`;
    }
    case "entry": {
      const verb = d.supersedes ? "Corrected" : "Entered";
      const field = `${layoutFieldText(d.field ?? "a fact")}${timeOf(d)}`;
      if (d.value === null) return `${verb} for ${field} (value withheld)`;
      const value = typeof d.value === "string" ? valueWord(d.value) : typeof d.value === "number" ? num(d.value) : String(d.value);
      return `${verb} ${value}${d.unit ? ` ${d.unit}` : ""} for ${field}`;
    }
    case "choice":
      return `Kept the ${layoutFieldInText(d.field ?? "value")}${timeOf(d)}${file ? ` of ${file}` : ""}; the files' other readings are not used`;
    case "link":
      return `${file || "A file"} is ${d.confirmed ? "" : "not "}about this ${kind}`;
    case "assign": {
      const to = Object.entries(d.linked_to).map(([role, label]) => `${ROLE_WORD[role] ?? role} ${label}`).join(", ");
      const still = d.current === null || d.values === null || d.current === d.values ? ""
        : d.current === 0 ? " (since linked elsewhere)" : ` (${d.current} of them still here)`;
      return `Linked ${plural(d.values ?? 0, "value")} of ${file || "a file"} to ${to || `this ${kind}`}${still}`;
    }
    case "not_data":
      return `Marked as not data: ${listed(d.places.map(placeText))} of ${file}`;
    case "restore":
      return `Given back (counted again): ${listed(d.places.map(placeText))} of ${file}`;
    case "layout":
      return `Table layout ${d.status ?? "decided"}: the ${tableKindText(d.table_kind)} of ${file || "no file now"}, version ${d.version ?? ""}`;
    default:
      return "A decision";
  }
}

/** Who decided it, when, and why: "dev-user, 15 Nov 2026, 10:21 · “a note about re-assays”". */
export const saidText = (d: Decision) => [`${d.by}, ${whenText(d.at)}`, d.why ? `“${d.why}”` : ""].filter(Boolean).join(" · ");

function Lines({ decisions, subject, testId }: { decisions: Decision[]; subject: Subject; testId?: string }) {
  return (
    <ul className="decision-list" data-testid={testId}>
      {decisions.map((d) => (
        <li key={`${d.kind}-${d.id}`} data-testid={`decision-${d.kind}-${d.id}`}>
          <span className="decision-what">{decisionText(d, subject)}</span>
          <span className="muted fs-12">{saidText(d)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Every decision `subject`'s signature binds, newest first: its own, then the delivery's other files in a fold. */
export function Decisions({ subject }: { subject: Subject }) {
  const own = subject.decisions.filter((d) => d.scope === "subject");
  const delivery = subject.decisions.filter((d) => d.scope === "delivery");
  const noun = subject.subject_type === "compound" ? "compound" : subject.subject_type;
  return (
    <section className="delivery-block card-section" data-testid={`delivery-decisions-${subject.subject}`}>
      <div className="delivery-block-head">
        <h3>Decisions made on this {noun}</h3>
        <span className="muted fs-13">{own.length ? plural(own.length, "decision") : "none yet"}</span>
      </div>
      {own.length === 0 ? <p className="muted m-0">No one has decided anything on it yet: what your signature binds is what its files say.</p> : (
        <>
          <p className="muted m-0 fs-13">Your signature binds these too. Each was made with its reason, kept on the audit trail.</p>
          <Lines decisions={own} subject={subject} testId={`delivery-decisions-own-${subject.subject}`} />
        </>
      )}
      {delivery.length > 0 && (
        <details className="decisions-delivery" data-testid={`delivery-decisions-others-${subject.subject}`}>
          <summary><span className="todo-caret" aria-hidden="true" />Your signature also binds the clean-up of the delivery&apos;s other
            files: {plural(delivery.length, "decision")}</summary>
          <Lines decisions={delivery} subject={subject} />
        </details>
      )}
    </section>
  );
}

/** What changed after the subject's confirmation was signed (final review INT-8): the decisions made since, each with
 *  who, when, why and in which file; "in the delivery's files" when the change is outside the subject's own. */
export function ChangedSince({ subject, children }: { subject: Subject; children?: ReactNode }) {
  const c = subject.confirmation;
  if (!c || c.current) return null;
  const since = subject.decisions.filter((d) => d.at > c.at);
  return (
    <div className="card-changed-since" data-testid={`card-changed-since-${subject.subject}`}>
      {children}
      {since.length ? (
        <>
          <p className="m-0">What changed since it was signed:</p>
          <ul className="decision-list">
            {since.map((d) => (
              <li key={`${d.kind}-${d.id}`} data-testid={`changed-${d.kind}-${d.id}`}>
                <span className="decision-what">{decisionText(d, subject)}{d.scope === "delivery" ? " (in the delivery's files)" : ""}</span>
                <span className="muted fs-12">{saidText(d)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : <p className="muted m-0">No person&apos;s decision was made since it was signed: one of the delivery&apos;s files was read again.</p>}
    </div>
  );
}
