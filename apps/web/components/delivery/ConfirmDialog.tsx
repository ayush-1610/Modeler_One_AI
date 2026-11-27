"use client";

// The signed confirmation of a subject (contracts 2026-11-12 §8.10; 21 CFR Part 11): the dialog says what the
// signature binds (the subject, its values by evidence level, the coverage of its files), what the landing holds back,
// any mapping no person approved, and the intake rules the record was computed with, which are UNVERIFIED until the SME
// signs them. Nothing is signed while a blocker or a landing problem exists: they are named here and the button is off.
// The signature needs the person's identity again (password and authenticator code): the API asks for it and the API
// client opens the step-up, then sends the confirmation once more. No password is typed on this page. A card confirmed
// before says what signing it again changes (`ConfirmImpact`), read before the signature.

import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { Dialog } from "@/components/kit/Dialog";
import { send } from "@/lib/api";
import { now } from "@/lib/hooks";
import { landingText, tableKindText } from "@/lib/words";

import {
  BLOCKER_LABEL, KIND_LABEL, Problem, WITHHELD, blockerDetail, levelText, plural, useDecide, type Blocker, type Page, type Subject,
} from "./shared";
import { ConfirmImpact } from "./ConfirmImpact";
import { pageKey, writeConfirmed } from "./writes";

// what holds a signature, in the card's words (the delivery's clean-up is one of them)
const BLOCKER_WORD: Record<string, string> = {
  SILENT_LOSS: "Numbers not read in the delivery's tables", OUTSIDE_NUMBERS: "Loose numbers in the delivery's files",
  UNASSIGNED_VALUES: "Values in the delivery's files not linked to a study", SCHEMA_GAP: "Facts not stated", CHECK_FAILED: "Checks to decide",
  LINK_UNCONFIRMED: "A link between files to decide", SPOT_CHECK: "The spot check",
};

const CONFIRM = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}:confirm" as const;

/** The coverage counts the record binds, added up over the files of the subject's deliveries. */
function coverageCounts(subject: Subject) {
  const sum = (pick: (c: Subject["coverage"][number]) => number) => subject.coverage.reduce((n, c) => n + pick(c), 0);
  return { files: subject.coverage.length, silent: subject.silent_loss, unread: sum((c) => c.regions_unread),
           outside: sum((c) => c.outside_numeric), unassigned: sum((c) => c.values_unassigned) };
}

export function ConfirmDialog({ projectId, subject, onClose }: { projectId: string; subject: Subject; onClose: () => void }) {
  const { decide, busy, problem } = useDecide();
  const client = useQueryClient();
  const [signed, setSigned] = useState<Subject | null>(null);
  const [refusedFor, setRefusedFor] = useState<Blocker[]>([]);
  // the delivery page as the signature found it, and when the signature was sent: what Done compares the page with
  const signing = useRef<{ before?: Page; sent: number } | null>(null);
  const counts = coverageCounts(subject);
  const blockers = refusedFor.length ? refusedFor : subject.blockers;
  const blocked = subject.blockers.length > 0 || subject.landing_problem !== null;
  const waiting = subject.mappings.filter((m) => m.status !== "approved");
  const levels = Object.entries(subject.by_level);

  async function sign() {
    if (busy) return;   // the button stays focusable while the signature is sent (final review A11Y-1)
    // a refusal names its blockers beside its message: they are listed, as the card's are. The page is read again when
    // this dialog closes, not while it says what was signed: read at once, the sheet form's group of the study (which the
    // landing marks confirmed) can answer before the delivery's page, the card then reads for a moment as one the sheet
    // form confirmed, and its delivery view, this dialog with it, leaves the page before the person has read it
    let named: Blocker[] = [];
    signing.current = { before: client.getQueryData<Page>(pageKey(projectId)), sent: now() };
    const { data } = await decide(async () => {
      const env = await send("post", CONFIRM, { project_id: projectId, type: subject.subject_type, subject: subject.subject });
      named = (env.errors[0]?.detail?.blockers as Blocker[] | undefined) ?? [];
      return env;
    }, {});
    setRefusedFor(named);
    if (data) setSigned(data);
  }
  const close = () => {
    if (signed) void writeConfirmed(client, projectId, signed, signing.current ?? {});
    onClose();
  };

  if (signed) {
    const landed = signed.confirmation?.landed;
    return (
      <Dialog title={`${subject.label} is confirmed`} size="narrow" onClose={close} testId="delivery-confirm-dialog" focusKey="signed">
        <p className="m-0" data-testid="delivery-signed">
          Signed: <strong>{signed.signature?.manifestation ?? signed.confirmation?.manifestation}</strong>
        </p>
        {landed ? (
          <p className="m-8-0-0" data-testid="delivery-landed">
            Loaded into the project: {plural(landed.datasets.length, "dataset")}, {plural(landed.evidence.length, "value")}
            {landed.dissolution_records ? `, ${plural(landed.dissolution_records, "dissolution record")}` : ""}.
            {landed.pending?.length ? ` Held back: ${landed.pending.join("; ")}.` : ""}
          </p>
        ) : (
          <p className="delivery-problem" role="alert">The signature is recorded but the loading did not finish: confirm again to
            finish it (no new signature is made).</p>
        )}
        <div className="dialog-actions"><button type="button" className="btn primary" onClick={close} data-testid="delivery-confirm-done">Done</button></div>
      </Dialog>
    );
  }

  return (
    <Dialog title={`Confirm ${KIND_LABEL[subject.subject_type].toLowerCase()} ${subject.label}`} size="narrow" onClose={onClose} testId="delivery-confirm-dialog"
            focusKey="confirm">
      <p className="muted">Your electronic signature (meaning: Reviewed) binds this record, and its values are then loaded into
        the project. You are asked for your password again (and your authenticator code, where your account uses one).</p>
      <dl className="delivery-facts" data-testid="delivery-confirm-record">
        <dt>You sign</dt><dd>{KIND_LABEL[subject.subject_type]} <strong>{subject.label}</strong></dd>
        <dt>Values</dt>
        <dd data-testid="delivery-confirm-values">{subject.values}{levels.length > 0 && <> ({levels.map(([level, n]) => `${n} ${levelText(level)}`).join(", ")})</>}</dd>
        <dt>From the files</dt>
        <dd data-testid="delivery-confirm-coverage">{plural(counts.files, "file")}: {plural(counts.silent, "number")} not read in their tables,
          {" "}{plural(counts.unread, "table or text", "tables or texts")} not read, {plural(counts.outside, "loose number")},
          {" "}{plural(counts.unassigned, "value")} not linked to a study</dd>
        <dt>Held back</dt>
        <dd data-testid="delivery-confirm-held">
          {subject.held === null ? WITHHELD : subject.held.length === 0 ? "nothing: every value that can be loaded is loaded"
            : <ul className="plain-list">{subject.held.map((h) => <li key={h}>{h}</li>)}</ul>}
        </dd>
        {waiting.length > 0 && (
          <>
            <dt>Table layouts not approved</dt>
            <dd data-testid="delivery-confirm-mappings">{waiting.map((m) => `${tableKindText(m.kind)}, version ${m.version} (${m.status === "rejected" ? "rejected" : "to approve"})`).join("; ")}</dd>
          </>
        )}
        <dt>Decisions</dt>
        <dd data-testid="delivery-confirm-decisions">
          {plural(subject.decisions.filter((d) => d.scope === "subject").length, "decision")} made on it
          {subject.decisions.some((d) => d.scope === "delivery")
            ? `, and ${plural(subject.decisions.filter((d) => d.scope === "delivery").length, "decision")} on the clean-up of the delivery's other files`
            : ""}{" "}(each listed on the card, with who, when and why)</dd>
        <dt>Intake rules</dt>
        <dd data-testid="delivery-confirm-rules">v{subject.rules.version}, {subject.rules.status}
          {subject.rules.status === "UNVERIFIED" && <span className="muted"> (SME sign-off pending)</span>}</dd>
      </dl>
      {/* a card confirmed before: what signing it again would load, set aside and make stale (slice 4c) */}
      {subject.confirmation && !subject.blinded && <ConfirmImpact projectId={projectId} subject={subject} />}
      {(blocked || refusedFor.length > 0) && (
        <div className="delivery-blocked" role="alert" data-testid="delivery-confirm-blockers">
          <strong>It cannot be signed yet:</strong>
          <ul className="plain-list">
            {blockers.map((b, i) => <li key={`${b.code}-${i}`}><strong>{BLOCKER_WORD[b.code] ?? BLOCKER_LABEL[b.code] ?? b.code}</strong>: {blockerDetail(b, subject)}</li>)}
            {subject.landing_problem && <li><strong>It cannot be loaded</strong>: {landingText(subject.landing_problem, subject.label)}</li>}
          </ul>
        </div>
      )}
      <Problem text={problem} testId="delivery-confirm-problem" />
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={onClose} data-testid="delivery-confirm-cancel">Cancel</button>
        {/* while it is sent, the button keeps the focus (aria-disabled, the click ignored): disabled, it would drop the focus
            to the page when the step-up gives it back, and Tab and Escape would leave this dialog (final review A11Y-1) */}
        <button type="button" className="btn primary" disabled={blocked} aria-disabled={busy || undefined} onClick={() => void sign()}
                data-testid="delivery-confirm-sign">{busy ? "Signing…" : "Sign and load"}</button>
      </div>
    </Dialog>
  );
}
