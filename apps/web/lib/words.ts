// One name per concept on Inputs (plan docs/plans/2026-11-14-inputs-task-first.md §2, rule 5; the design text's
// "Words"): the four status words, the areas, the model checks and the plain words that stand in for the engine's. Pure
// (no React): lib/inputsWork.ts, the Inputs page and its tests read the same words. A word that names a PK-Sim or intake
// vocabulary entry is keyed by that entry as the API sends it (harvested, never invented); an entry with no word here is
// shown as sent, its underscores turned to spaces.

/** The four status words: only these on chips, counts and filters (design "Status words"). */
export type Status = "missing" | "to_confirm" | "to_decide" | "done";
export const STATUS_WORD: Record<Status, string> = {
  missing: "Missing", to_confirm: "To confirm", to_decide: "To decide", done: "Done",
};
/** What each word means, said where it is counted (a count's title). */
export const STATUS_MEANS: Record<Status, string> = {
  missing: "No file or source gives it: you fill it in",
  to_confirm: "The client's data wait for your sign-off",
  to_decide: "A choice only you can make: a table layout, values to link, numbers to set aside, a disagreement",
  done: "Confirmed, entered or settled",
};
/** A status chip's tone: amber only where a person must decide or sign (plan §2, rule 5); done is green. */
export const STATUS_TONE: Record<Status, string> = { missing: "high", to_confirm: "medium", to_decide: "medium", done: "low" };

/** The areas of Inputs, in the area bar's order (ids are PK-Sim's building blocks; `todo` and `files` are the page's). */
export type Tab = "todo" | "compound" | "formulations" | "studies" | "individuals" | "settings" | "files";
export const AREA_NAME: Record<Tab, string> = {
  todo: "To do", compound: "Compound", formulations: "Products and dissolution", studies: "Clinical studies",
  individuals: "Populations and individuals", settings: "Simulation settings", files: "Client files",
};
export const AREAS: Tab[] = ["todo", "compound", "formulations", "studies", "individuals", "settings", "files"];

export const plural = (n: number, word: string, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
const spaced = (text: string) => text.replace(/_/g, " ");

// --- the model checks (the readiness report) and the step bar's line ---------------------------------------------------

/** A readiness check in words, keyed by its raw name without the reference in brackets ("S0 completeness (MS-01
 *  §2.2)" is keyed "S0 completeness"); `what` says it in a sentence, `fix` where it is settled. */
const CHECKS: Record<string, { label: string; waiting: string; fix: string }> = {
  "assembly": { label: "Inputs put together", waiting: "the inputs could not be put together",
                fix: "Put together from every source; a problem names its source." },
  "S0 completeness": { label: "Minimum compound data", waiting: "compound values missing",
                       fix: "Fill them in on Compound, or search the sources and the literature." },
  "every pathway placeable": { label: "Each elimination pathway maps to a PK-Sim process", waiting: "an elimination pathway has no PK-Sim process",
                               fix: "Choose its process on Compound." },
  "expression profiles": { label: "Enzyme and transporter expression", waiting: "enzyme or transporter expression missing",
                           fix: "Set on Populations and individuals." },
  "formulations of solid studies": { label: "A formulation for each tablet study", waiting: "a tablet study has no formulation",
                                     fix: "Choose it on Products and dissolution." },
  "multiple-dose regimens": { label: "Dosing of multiple-dose studies", waiting: "the dosing of a multiple-dose study is missing",
                              fix: "Fill it in on its study." },
  "demographics stated": { label: "Demographics of confirmed studies", waiting: "the demographics of a study are missing",
                           fix: "Enter them on Populations and individuals, or ask the client." },
  "observed data to judge on": { label: "Observed data to compare the model with", waiting: "no observed data confirmed yet",
                                 fix: "Confirm a study's data on Clinical studies, or add data." },
  "observed data are real": { label: "Observed data are real, not test data", waiting: "some observed data are test data",
                              fix: "Leave the test data out on Clinical studies." },
  "every planned simulation builds": { label: "All planned simulations build", waiting: "the model can't be built yet",
                                       fix: "Follows once the values above are in." },
};
const checkKey = (raw: string) => raw.replace(/\s*\([^)]*\)\s*$/, "");

/** A model check's label in words ("Minimum compound data (6 missing)" with its detail's count). */
export function checkLabel(raw: string, detail: string[] = [], ok = true): string {
  const known = CHECKS[checkKey(raw)];
  if (!known) return spaced(raw);
  return !ok && checkKey(raw) === "S0 completeness" && detail.length ? `${known.label} (${detail.length} missing)` : known.label;
}
/** Where an open check is settled, in a sentence. */
export const checkFix = (raw: string) => CHECKS[checkKey(raw)]?.fix ?? "";
/** A reason the step bar gives for Inputs (a raw check name, or the step's own sentence), in plain words. */
export const stepReason = (raw: string) => CHECKS[checkKey(raw)]?.waiting ?? raw;

// --- the compound's and the studies' open items (the /inputs to-do) ----------------------------------------------------

/** A model input's name in words, by its CPF id (the ids the to-do names). */
export const PARAM_LABEL: Record<string, string> = {
  "phys.mw": "Molecular weight", "phys.logp": "Lipophilicity", "bind.fu": "Fraction unbound in plasma",
  "phys.solubility.ref": "Reference solubility", "phys.pka": "pKa", elim: "An elimination pathway",
  "perm.intestinal": "Intestinal permeability", "elim.renal.gfr_fraction": "GFR fraction (renal filtration)",
  "elim.biliary.cl": "Biliary clearance", "dist.bp_ratio": "Blood-to-plasma ratio",
  "elim.fe_urine": "Fraction excreted unchanged in urine (fe)", "elim.fm.<enzyme>": "Fraction metabolized by an enzyme (fm)",
};
export const paramLabel = (id: string) => PARAM_LABEL[id] ?? id;

/** An open item of the /inputs to-do in words (its kind and target). */
export function todoLabel(kind: string, target: string): string {
  const p = paramLabel(target);
  switch (kind) {
    case "missing": return p;
    case "conflict": return `${p}: the sources disagree more than 2-fold, keep one`;
    case "correct": return `${p}: filed under the wrong parameter?`;
    case "pka": return "pKa: acidic or basic?";
    case "review": return `${p}: check this value before it is used`;
    case "formulation": return "The formulation of the tablet studies";
    case "process": return `${p}: which PK-Sim process carries the pathway?`;
    case "unit": return `${p}: a unit to convert`;
    case "datasets": return "Observed data to compare the model with";
    case "regimen": return `Dosing of the multiple-dose study ${target}`;
    case "demographics": return `Demographics of study ${target}`;
    case "check": return "The model can't be built yet";
    case "confirm": return `Confirm ${target}`;
    default: return `${spaced(kind)} · ${p}`;
  }
}

// --- the client's files and the delivery's reading ----------------------------------------------------------------------

/** A table's kind (the intake's `TableKind`, modeler_intake.fields) in words. */
const TABLE_KIND: Record<string, string> = {
  pk_individual: "individual PK table", pk_summary: "PK summary table", pk_parameters: "PK parameters table",
  dissolution: "dissolution table", study_design: "study design table", demographics: "demographics table",
  product_batch: "product and batch table", bioanalytical: "bioanalytical table", physchem_invitro: "physico-chemistry and in vitro table",
  excretion: "excretion table", composition: "composition table", ddi_relation: "drug-interaction table",
  not_data: "notes, not data", unknown: "table of unknown kind",
};
export const tableKindText = (kind: string | null | undefined) => (kind ? TABLE_KIND[kind] ?? spaced(kind) : "table");

/** Who suggested a table layout (a mapping's `origin`). */
export const layoutOrigin = (origin: string) =>
  origin === "rule" ? "suggested by the template rules" : origin === "llm" ? "suggested automatically" : "entered by a person";

/** Where in a file, as a person reads it: "Sheet1 · A4:M12", "page 3" (never the raw locator s:'Sheet1'!A4:M12). */
export function placeText(where: string): string {
  const sheet = /^s:'((?:[^']|'')+)'!(.+)$/.exec(where);
  if (sheet) return `${sheet[1].replace(/''/g, "'")} · ${sheet[2]}`;
  const page = /^p:(\d+)/.exec(where);
  if (page) return `page ${page[1]}`;
  return where.replace(/^[a-z]:/, "");
}

/** The engine's words on the delivery, in a person's (design "One name per concept"). */
export const DELIVERY_WORDS = {
  notRead: "numbers not read",          // silent loss: in tables, but no column picked them up
  loose: "loose numbers",               // outside numbers: in notes or text, outside any table
  unlinked: "values not linked to a study",
  layout: "table layout",
  notData: "not data",
} as const;

/** The intake rules, as the chip says them: "Intake rules v0.1 · UNVERIFIED" (UNVERIFIED stays upper case: CLAUDE.md). */
export const rulesText = (rules: { version: string; status: string }) => `Intake rules v${rules.version} · ${rules.status}`;

/** A date and time as a person reads it: "14 Nov 2026, 18:15" (UTC, as recorded). */
export function whenText(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getUTCMonth()];
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCDate()} ${month} ${d.getUTCFullYear()}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
