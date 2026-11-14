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
  // the other model inputs of the parameter registry (pbpk_domain/parameters/registry.yaml), in plain words
  "bind.partner": "Plasma protein binding partner", "phys.solubility.table": "Solubility vs pH table",
  "phys.solubility.ref_ph": "pH of the reference solubility", "phys.pka.neutral": "Neutral compound (no pKa)",
  "elim.ehc_fraction": "Enterohepatic recycling (EHC continuous fraction)", "perm.cellular": "Cellular permeability",
  "dist.partition_method": "Partition coefficient method", "dist.permeability_method": "Cellular permeability method",
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

/** A spreadsheet column's letters as its number (A 1, Z 26, AA 27). */
const columnNumber = (letters: string) => [...letters].reduce((n, c) => n * 26 + c.charCodeAt(0) - 64, 0);

export type FilePlace = { name: string; place: string; columns: number | null; rows: number | null; start: number | null };

/** Where a table, a paragraph or a note is in its file (a region's `where`, an outside item's locator, the intake
 *  grammar's ranges and locators), in plain words: its short name ("Sheet1", "page 3, table 1"), the place in full
 *  ("sheet Sheet1, cells A4 to M12") and, for a sheet range, its size and the sheet column it starts at (A: 1). A text
 *  outside the grammar is given as it is. */
export function whereIs(where: string): FilePlace {
  const sheet = /^s:'((?:[^']|'')+)'!([A-Z]{1,3})([0-9]+)(?::([A-Z]{1,3})([0-9]+))?$/.exec(where);
  if (sheet) {
    const [, quoted, c0, r0, c1, r1] = sheet;
    const name = quoted.replace(/''/g, "'");
    if (!c1) return { name, place: `sheet ${name}, cell ${c0}${r0}`, columns: null, rows: null, start: columnNumber(c0) };
    return { name, place: `sheet ${name}, cells ${c0}${r0} to ${c1}${r1}`, columns: columnNumber(c1) - columnNumber(c0) + 1,
             rows: Number(r1) - Number(r0) + 1, start: columnNumber(c0) };
  }
  const words: [RegExp, (m: RegExpExecArray) => string][] = [
    [/^p:(\d+)\/t:(\d+)/, (m) => `page ${m[1]}, table ${m[2]}`],
    [/^p:(\d+)\/f:(\d+)/, (m) => `page ${m[1]}, figure ${m[2]}`],
    [/^p:(\d+)\/w:/, (m) => `page ${m[1]}`],
    [/^d:t:(\d+)/, (m) => `table ${m[1]}`],
    [/^d:f:(\d+)/, (m) => `figure ${m[1]}`],
    [/^d:p:(\d+)-(\d+)$/, (m) => `paragraphs ${m[1]} to ${m[2]}`],
    [/^d:p:(\d+)\//, (m) => `paragraph ${m[1]}`],
    [/^x:l:(\d+)-(\d+)$/, (m) => `lines ${m[1]} to ${m[2]}`],
    [/^x:l:(\d+)\//, (m) => `line ${m[1]}`],
  ];
  for (const [rule, say] of words) {
    const m = rule.exec(where);
    if (m) return { name: say(m), place: say(m), columns: null, rows: null, start: null };
  }
  return { name: where, place: where, columns: null, rows: null, start: null };
}

/** Where in a file, as a person reads it ("sheet Sheet1, cells A4 to M12", "page 3, table 1"), never the raw locator. */
export const placeText = (where: string) => whereIs(where).place;

/** A fact a study record needs (the intake's field, as a gap's `tag` or a check's "needs <field>" names it), in words:
 *  the sheet form's own labels for the same facts and the landing's "(what the study is for)". */
const FACT_WORD: Record<string, string> = {
  n: "the number of subjects", intended_use: "what the study is for", purpose: "what the study is for", route: "the route",
  dose: "the dose", formulation: "the dosage form", food_state: "fasted or fed",
};
export const factText = (field: string) => FACT_WORD[field] ?? `the ${spaced(field)}`;

/** A reading stage (the intake pipeline's `StageName`, modeler_project.intake_records) in words. */
const STAGE_WORD: Record<string, string> = {
  parse: "finding the tables and texts", map: "choosing each table's layout", map_llm: "layouts suggested automatically",
  execute: "reading the tables", prose: "reading the text", ledger: "recording the values", compute: "deriving values",
  checks: "checking the values", coverage: "accounting for every number",
};
export const stageText = (stage: string) => STAGE_WORD[stage] ?? spaced(stage);
/** A stage's or a count's own text from the reader, its engine terms in a person's words ("silent loss 10" → "numbers not
 *  read 10"). Only these terms are replaced; the rest is shown as the reader wrote it. */
export const engineWords = (text: string) => text
  .replace(/silent loss/g, "numbers not read").replace(/outside numbers/g, "loose numbers")
  .replace(/unassigned values/g, "values not linked to a study").replace(/\bregions\b/g, "tables and texts").replace(/\bregion\b/g, "table or text");

/** The engine's words on the delivery, in a person's (design "One name per concept"). */
export const DELIVERY_WORDS = {
  notRead: "numbers not read",          // silent loss: in tables, but no column picked them up
  loose: "loose numbers",               // outside numbers: in notes or text, outside any table
  unlinked: "values not linked to a study",
  layout: "table layout",
  notData: "not data",
} as const;

// --- a study's and a product's facts, as a person fills them in (plan 2026-11-14 slice 3, FactsForm) ------------------

/** A fact's label in a form or a list, by the intake field it is entered under (`modeler_intake.fields`, the names
 *  `:enter` takes; the sheet form's need names `purpose` and `dose` read the same): "Number of subjects", never `n`. */
const FIELD_LABEL: Record<string, string> = {
  n: "Number of subjects", n_evaluable: "Evaluable subjects", intended_use: "Purpose of the study", purpose: "Purpose of the study",
  route: "Route", dose: "Dose", dose_unit: "Dose unit", formulation: "Dosage form", food_state: "Fasted or fed", design: "Design",
  matrix: "Matrix", lloq: "LLOQ", analyte: "Analyte", infusion_time_min: "Infusion time (min)",
  dosing_interval_h: "Dosing interval (h)", n_doses: "Number of doses", population: "Population",
  age_mean: "Mean age (years)", age_min: "Youngest (years)", age_max: "Oldest (years)", weight_mean_kg: "Mean weight (kg)",
  height_mean_cm: "Mean height (cm)", percent_female: "Women (%)", n_female: "Number of women", ethnicity: "Ethnicity",
  product_role: "Role", strength_mg: "Strength (mg)", dosage_form: "Dosage form", release: "Release", batch: "Batch",
  particle_size_d50_um: "Particle size d50 (µm)", polymorph: "Polymorph", salt_form: "Salt form",
  apparatus: "Apparatus", medium: "Medium", ph: "pH", rpm: "Stirring (rpm)", volume_ml: "Volume (mL)",
};
export const fieldLabel = (field: string) => FIELD_LABEL[field] ?? `${spaced(field).charAt(0).toUpperCase()}${spaced(field).slice(1)}`;

/** A vocabulary entry in words (the study record's enums, the intake vocabulary's choices and the brief's purposes, as
 *  the API sends them in `study_options` or a field's `choices`); an entry with no word is shown as sent. */
const VALUE_WORD: Record<string, string> = {
  oral: "Oral", iv_bolus: "IV bolus", iv_infusion: "IV infusion", other: "Other",
  solution: "Solution", suspension: "Suspension", ir_tablet: "IR tablet", ir_capsule: "IR capsule", mr: "Modified release",
  fasted: "Fasted", fed: "Fed", SD: "Single dose", MD: "Multiple dose",
  model_building: "Model building", internal_validation: "Internal validation", external_validation: "External validation",
  application_verification: "Application verification", supportive: "Supportive",
  plasma: "Plasma", blood: "Blood", serum: "Serum", urine: "Urine", feces: "Feces",
  healthy: "Healthy", patient: "Patients", TEST: "Test", RLD: "RLD", REFERENCE: "Reference", SOLUTION: "Solution", OTHER: "Other",
  arithmetic_mean: "arithmetic mean", geometric_mean: "geometric mean", median: "median",
};
export const valueWord = (value: string) => VALUE_WORD[value] ?? spaced(value);

/** How a study is given, as the Clinical studies list groups it (plan 2026-11-14 §2.2.8): by the facts its files or its
 *  sheet form state; a study whose route is not stated yet is under "Other". */
export type Design = "iv" | "oral_fasted" | "oral_fed" | "multiple" | "other";
export const DESIGNS: Design[] = ["iv", "oral_fasted", "oral_fed", "multiple", "other"];
export const DESIGN_TITLE: Record<Design, string> = {
  iv: "IV", oral_fasted: "Oral, fasted", oral_fed: "Oral, fed", multiple: "Multiple dose", other: "Other or not stated yet",
};
export function designOf(facts: { route?: unknown; food_state?: unknown; design?: unknown }): Design {
  const route = String(facts.route ?? "");
  if (route.startsWith("iv")) return "iv";
  if (String(facts.design ?? "") === "MD") return "multiple";
  if (route === "oral") return String(facts.food_state ?? "") === "fed" ? "oral_fed" : facts.food_state ? "oral_fasted" : "other";
  return "other";
}

/** A requirement item's disposition (`DeliveryDisposition.disposition`) in words. */
export const DISPOSITION_WORD: Record<string, string> = {
  ask_client: "asked of the client", literature: "taken from the literature", not_needed: "not needed for this model",
};

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
