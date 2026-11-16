"use client";

// A study's one card (plan 2026-11-14 slice 3; the design text's StudyCard), opened under its row in the Clinical studies
// list: whichever reader found the study, its confirm path (ConfirmPath), its observed data (the sheet form's profiles
// drawn, and the study's datasets with where each stands), its files, and the other reader's view folded. A compound's
// card is the same, on Compound.

import type { ReactNode } from "react";

import { blindedWhy, cardAnchor, normLabel, type Subject } from "@/lib/inputsWork";
import { sourceNamed } from "@/lib/words";

import { DatasetView } from "../DatasetView";
import { StudyDatasets, useStudyDatasets } from "../ObservedDatasets";

import { CardHead, ConfirmPath, cardStatus, viaSheet, type CardEnv } from "./ConfirmPath";

/** The names a dataset of this study is stored under: its label and the names the other reader gave it. */
export const studyNames = (s: Subject) => {
  const names = new Set([s.label, ...s.aliases, ...s.groups.map((g) => g.title.replace(/^Study /, ""))].map(normLabel));
  return (studyId: string) => names.has(normLabel(studyId));
};

/** The files a card was read from, by name, each opening its row in Client files. */
export function CardFiles({ subject, env }: { subject: Subject; env: CardEnv }) {
  const names = subject.files.map((id) => [id, env.fileName?.(id) ?? null] as const).filter(([, n]) => n);
  if (!names.length) return null;
  return (
    <p className="card-files fs-13 m-0" data-testid={`card-files-${subject.key}`}>
      <span className="muted">Read from </span>
      {names.map(([id, name], i) => (
        <span key={id}>{i > 0 && ", "}
          {/* named with the card: one file can hold every study's data, and so be named on each card (round 4) */}
          {env.onFile ? <button type="button" className="link-btn" onClick={() => env.onFile!(id)}
                                aria-label={`${name}: open it in Client files (read from it: ${subject.kind} ${subject.label})`}
                                title={`Open ${name} in Client files`}>{name}</button> : name}
        </span>
      ))}
    </p>
  );
}

/** The observed data of a study on its card: the sheet form's profiles (drawn) when the study is confirmed on the
 *  delivery (on a sheet-form card they are drawn in its group), and every dataset of the study with where it stands.
 *  Nothing on a sheet-form card whose study has no dataset yet (its data are in its group, below). */
function Observed({ subject: s, env, unpromised }: { subject: Subject; env: CardEnv; unpromised: string[] }) {
  const delivery = s.path === "delivery" && !viaSheet(s);
  const drawn = delivery ? s.groups.flatMap((g) => g.items.filter((i) => i.kind !== "draft" && i.data).map((i) => ({ g, i }))) : [];
  const datasets = useStudyDatasets(env.projectId, studyNames(s));
  // why the card says the study is blinded, on its visible withheld line (the delivery's, or the sheet form's group's):
  // a dataset blinded for the same reason does not say it again (round 7: one sentence per fact on a card)
  const said = !s.blinded ? null : delivery ? (s.row?.blinded ? s.row.blinded_why ?? null : null) : blindedWhy(s);
  if (!delivery && !datasets?.length) return null;
  return (
    <section className="delivery-block card-section" data-testid={`card-observed-${s.key}`}>
      <div className="delivery-block-head"><h3>Observed data</h3></div>
      {drawn.map(({ g, i }) => <DatasetView key={i.id} data={i.data!} label={sourceNamed(`${g.title}: ${i.label}`, i.source)} />)}
      {datasets && <StudyDatasets datasets={datasets} projectId={env.projectId} run={env.run} unpromised={unpromised} said={said} />}
      {!drawn.length && delivery && (
        <p className="muted m-0 fs-13">Its profile is drawn here once it is in the model; the values read from its files are under
          Files and tables.</p>
      )}
    </section>
  );
}

export function StudyCard({ subject, env, unpromised = [], onShow, files }: {
  subject: Subject; env: CardEnv; unpromised?: string[];
  /** bring the study's row in "In the model" into view */
  onShow?: () => void;
  files?: ReactNode;
}) {
  return (
    <div className="subject-card study-card" data-testid={cardAnchor(subject)} id={cardAnchor(subject)} data-path={subject.path}>
      <ConfirmPath subject={subject} env={env} onShow={subject.done ? onShow : undefined} files={files ?? <CardFiles subject={subject} env={env} />}
                   observed={<Observed subject={subject} env={env} unpromised={unpromised} />} />
    </div>
  );
}

/** The compound's card on Compound: the client's compound values, read by either reader, confirmed on it. */
export function CompoundCard({ subject, env, open, onToggle }: { subject: Subject; env: CardEnv; open: boolean; onToggle: () => void }) {
  return (
    <article className="subject-card compound-card" data-testid={cardAnchor(subject)} id={cardAnchor(subject)} data-path={subject.path}>
      <CardHead subject={subject} status={cardStatus(subject, env.work)} open={open} onToggle={onToggle} />
      {open && <div id={`${cardAnchor(subject)}-body`}><ConfirmPath subject={subject} env={env} /></div>}
    </article>
  );
}
