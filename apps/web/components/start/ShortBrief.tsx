"use client";

import { Block, Fields, OpenQuestions } from "@/components/start/Blocks";
import type { BriefView } from "@/lib/brief";
import type { Open, Save } from "@/lib/start";

const QUESTION = ["qoi.text", "qoi.context_of_use", "qoi.applications"];
const DRUG = ["drug.bcs_class", "scope.pathways", "scope.pathways_stated", "scope.nonlinearity", "scope.ehc"];

/** Block 2: the short brief, filled by the intake agent from the documents. Every value shows the words it was read
 *  from (opened on its page beside); the person changes only what is wrong. */
export function ShortBrief({ view, save, open, onAnswer }: {
  view: BriefView; save: Save; open: Open;
  onAnswer: (id: string, text: string, status: "answered" | "accepted_as_limitation") => void;
}) {
  return (
    <Block n={2} title="The question" testId="start-brief"
           lede="Read from the proposal: each value cites the words it came from. Change only what is wrong; nothing asks why.">
      <Fields view={view} paths={QUESTION} save={save} open={open} />
      <h3 className="start-sub">The drug's disposition, as the proposal states it</h3>
      <Fields view={view} paths={DRUG} save={save} open={open} notApplicable={["scope.nonlinearity"]}
              suggestions={{ "scope.pathways_stated": view.start.pathway_suggestions }} />
      <p className="muted start-hint">
        The kinds of pathway decide the checklist's items (a renal pathway asks for urine data); the enzymes and
        transporters named shape the review. Which parameters S1–S3 may fit stays with the SME rules.
      </p>
      <OpenQuestions view={view} fields={new Set(view.catalog.short_brief)} onAnswer={onAnswer} />
    </Block>
  );
}
