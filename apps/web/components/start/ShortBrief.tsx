"use client";

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Block, Fields } from "@/components/start/Blocks";
import { NeedsYou, QuestionRow, Seg, Source } from "@/components/start/FieldRow";
import type { BriefView } from "@/lib/brief";
import { defOf, recordOf, valueOf, type BriefChange, type Marks, type Open, type Save } from "@/lib/start";

const QUESTION = ["qoi.text", "qoi.context_of_use", "qoi.applications"];

/** Each chosen application with its plain name and the data it adds to what the model needs (page review 1). */
function ApplicationsAdd({ view }: { view: BriefView }) {
  const chosen = (valueOf(view, "qoi.applications") as string[] | null) ?? [];
  const apps = view.start.applications.filter((a) => chosen.some((c) => c === a.option || c === a.code));
  if (!apps.length) return null;
  return (
    <ul className="app-adds" data-testid="start-app-adds">
      {apps.map((a) => (
        <li key={a.code}><strong>{a.name}</strong>{a.adds.length ? `: + ${a.adds.join(", ")}` : ": nothing beyond the core data"}</li>
      ))}
    </ul>
  );
}

// --- the pathways: one list, each named enzyme, transporter or route with its kind --------------------------------

const KIND_WORDS: [RegExp, string][] = [
  [/tubular secretion|secret/i, "renal_secretion"],
  [/renal|kidney|glomerular|\bgfr\b|urin/i, "renal_filtration"],
  [/biliary|bile|f(a)?ec/i, "biliary_excretion"],
  [/\bgut\b|intestin|enterocyte/i, "gut_wall_metabolism"],
  [/oatp|p-gp|\bpgp\b|bcrp|\boct\d|\boat\d|\bmate\d?|\bmrp\d|abc[a-z]\d|transporter|\bslc/i, "transporter_mediated"],
  [/cyp|ugt|sult|fmo|aldehyde oxidase|metaboli|glucuronid|hepatic|liver/i, "hepatic_metabolism"],
];
const SUFFIX = / \(([^()]+)\)$/;

type Row = { name: string; kind: string };

function kindOf(name: string): string {
  return KIND_WORDS.find(([rx]) => rx.test(name))?.[1] ?? "other";
}

function names(view: BriefView): string[] {
  const stated = valueOf(view, "scope.pathways_stated");
  if (Array.isArray(stated)) return stated.map(String);
  return typeof stated === "string" ? stated.split(/;|\n/).map((s) => s.trim()).filter(Boolean) : [];
}

/** The rows the two brief fields make: each stated name with its kind (written after it, else read from the name), then
 *  each kind no name falls under. */
function rows(view: BriefView, labels: Record<string, string>): Row[] {
  const byLabel = Object.fromEntries(Object.entries(labels).map(([k, v]) => [v, k]));
  const named = names(view).map((n) => {
    const m = SUFFIX.exec(n);
    return m && byLabel[m[1]] ? { name: n.replace(SUFFIX, ""), kind: byLabel[m[1]] } : { name: n, kind: kindOf(n) };
  });
  const kinds = ((valueOf(view, "scope.pathways") as string[] | null) ?? []).filter((k) => !named.some((r) => r.kind === k));
  return [...named, ...kinds.map((kind) => ({ name: "", kind }))];
}

/** The two brief fields from the rows: the kinds, and each name (with its kind written after it when the name alone
 *  would read as another kind, so the data checklist's pathway conditions read it as the person chose). */
function pathwayChanges(list: Row[], options: string[], labels: Record<string, string>): BriefChange[] {
  const kinds = options.filter((o) => list.some((r) => r.kind === o));
  const stated = list.filter((r) => r.name.trim())
    .map((r) => (kindOf(r.name) === r.kind ? r.name.trim() : `${r.name.trim()} (${labels[r.kind] ?? r.kind})`));
  return [
    kinds.length ? { path: "scope.pathways", status: "EDITED", value: kinds } : { path: "scope.pathways", status: "MISSING" },
    stated.length ? { path: "scope.pathways_stated", status: "EDITED", value: stated }
      : { path: "scope.pathways_stated", status: "MISSING" },
  ];
}

function Pathways({ view, save, open, marks }: { view: BriefView; save: Save; open: Open; marks: Marks }) {
  const def = defOf(view, "scope.pathways");
  const labels = def.option_labels;
  const current = rows(view, labels);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Row[]>(current);
  const [problem, setProblem] = useState<string | null>(null);
  const paths = ["scope.pathways", "scope.pathways_stated"];
  const issues = paths.flatMap((p) => marks.issues(p));
  const questions = paths.flatMap((p) => marks.questions(p));
  // the two fields' sources, each said once (both are usually set together, by the same person or quote)
  const sources = paths.map((p) => recordOf(view, p)).filter((r, i, all) => all.findIndex((o) =>
    o.by === r.by && o.status === r.status && JSON.stringify(o.citations) === JSON.stringify(r.citations)) === i);

  async function commit(list: Row[]) {
    const refused = await save(pathwayChanges(list, def.options, labels));
    setProblem(refused);
    if (!refused) setEditing(false);
  }

  return (
    <div className={`sb-row${issues.length || questions.length ? " needs-you" : ""}`} data-testid="start-field-pathways">
      <div className="sb-label">Elimination and transport pathways</div>
      <div className="sb-value">
        {editing ? (
          <div className="sb-editor">
            {draft.map((r, i) => (
              <div key={i} className="pathway-edit">
                <select aria-label={`Kind of pathway ${i + 1}`} value={r.kind} data-testid={`pathway-kind-${i}`}
                        onChange={(e) => setDraft(draft.map((x, j) => (j === i ? { ...x, kind: e.target.value } : x)))}>
                  {def.options.map((o) => <option key={o} value={o}>{labels[o] ?? o}</option>)}
                </select>
                <input value={r.name} list="pathway-names" placeholder="enzyme or transporter (optional)"
                       aria-label={`Name of pathway ${i + 1}`} data-testid={`pathway-name-${i}`}
                       onChange={(e) => setDraft(draft.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <button type="button" className="btn" aria-label={`Remove pathway ${i + 1}`}
                        onClick={() => setDraft(draft.filter((_, j) => j !== i))}>×</button>
              </div>
            ))}
            <datalist id="pathway-names">{view.start.pathway_suggestions.map((s) => <option key={s} value={s} />)}</datalist>
            <div className="row">
              <button type="button" className="btn" data-testid="pathway-add"
                      onClick={() => setDraft([...draft, { name: "", kind: def.options[0] }])}>Add a pathway</button>
              <button type="button" className="btn primary" data-testid="pathway-save" onClick={() => commit(draft)}>Save</button>
              <button type="button" className="btn" onClick={() => { setEditing(false); setProblem(null); }}>Cancel</button>
            </div>
            {problem && <InlineIssue severity="error">{problem}</InlineIssue>}
          </div>
        ) : current.length ? (
          <ul className="pathway-list" data-testid="pathway-list">
            {current.map((r, i) => (
              <li key={i}>{r.name ? <><strong>{r.name}</strong> · </> : null}<span className="muted">{labels[r.kind] ?? r.kind}</span></li>
            ))}
          </ul>
        ) : <span className="sb-missing">not set</span>}
        {!editing && sources.map((r, i) => <Source key={i} record={r} open={open} />)}
        {!editing && view.start.pathways_not_named.map((name) => (
          <InlineIssue key={name} testId={`pathway-not-named-${name}`}>
            The published model also has <strong>{name}</strong>, which the proposal does not name.{" "}
            <button type="button" className="link-btn" onClick={() => commit([...current, name === "renal elimination"
              ? { name: "", kind: "renal_filtration" } : { name, kind: kindOf(name) }])}>Add it</button>
          </InlineIssue>
        ))}
        <NeedsYou issues={issues} />
        {questions.map((q) => <QuestionRow key={q.id} q={q} onAnswer={marks.answer} />)}
      </div>
      {!editing && (
        <button type="button" className="btn sb-change" data-testid="edit-pathways"
                onClick={() => { setDraft(current.length ? current : [{ name: "", kind: def.options[0] }]); setEditing(true); }}>
          {current.length ? "Change" : "Set"}
        </button>
      )}
    </div>
  );
}

/** Yes, no or not stated, for what the proposal says about nonlinearity or enterohepatic recycling (page review 1). For
 *  nonlinearity "no" is stored as not applicable (linear PK: no Km or Vmax asked), "yes" keeps the proposal's words. */
function Stated({ path, label, view, save, open, marks }: {
  path: "scope.nonlinearity" | "scope.ehc"; label: string; view: BriefView; save: Save; open: Open; marks: Marks;
}) {
  const record = recordOf(view, path);
  const value = valueOf(view, path);
  const text = path === "scope.nonlinearity";
  const state = record.status === "NOT_APPLICABLE" || value === false ? "no"
    : value === true || (text && typeof value === "string" && value.trim()) ? "yes" : "not_stated";
  const [picked, setPicked] = useState(state);
  const issues = marks.issues(path);
  const questions = marks.questions(path);

  function pick(option: string) {
    setPicked(option);
    if (option === state) return;
    const change: BriefChange = option === "not_stated" ? { path, status: "MISSING" }
      : option === "no" ? (text ? { path, status: "NOT_APPLICABLE" } : { path, status: "EDITED", value: false })
        : { path, status: "EDITED", value: text ? "nonlinear pharmacokinetics stated" : true };
    void save([change]);
  }

  return (
    <div className={`sb-row${issues.length || questions.length ? " needs-you" : ""}`} data-testid={`start-field-${path}`}>
      <div className="sb-label">{label}</div>
      <div className="sb-value">
        <Seg options={["yes", "no", "not_stated"]} value={picked} onPick={pick} testId={`stated-${path}`} />
        {text && state === "yes" && typeof value === "string" && <span className="sb-text">{value}</span>}
        <Source record={record} open={open} />
        <NeedsYou issues={issues} />
        {questions.map((q) => <QuestionRow key={q.id} q={q} onAnswer={marks.answer} />)}
      </div>
      <span />
    </div>
  );
}

/** Block 2: the question and the drug's disposition, filled by the intake agent from the documents. Every value shows the
 *  words it was read from; the person changes only what is wrong. A field that waits on the person is marked red. */
export function ShortBrief({ view, save, open, marks }: { view: BriefView; save: Save; open: Open; marks: Marks }) {
  return (
    <Block n={2} title="The question" testId="start-brief">
      <Fields view={view} paths={QUESTION} save={save} open={open} marks={marks}
              extras={{ "qoi.applications": <ApplicationsAdd view={view} /> }} />
      <h3 className="start-sub">The drug's disposition, as the proposal states it</h3>
      <Fields view={view} paths={["drug.bcs_class"]} save={save} open={open} marks={marks} />
      <div className="sb-rows">
        <Pathways key={`${recordOf(view, "scope.pathways").at ?? ""}|${recordOf(view, "scope.pathways_stated").at ?? ""}`}
                  view={view} save={save} open={open} marks={marks} />
        <Stated key={`n:${recordOf(view, "scope.nonlinearity").at ?? ""}`} path="scope.nonlinearity"
                label="Nonlinearity stated (saturation, auto-induction)" view={view} save={save} open={open} marks={marks} />
        <Stated key={`e:${recordOf(view, "scope.ehc").at ?? ""}`} path="scope.ehc" label="Enterohepatic recycling stated"
                view={view} save={save} open={open} marks={marks} />
      </div>
    </Block>
  );
}
