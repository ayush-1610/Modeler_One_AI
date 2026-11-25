// The Data room's words and small helpers (plan 2026-11-21 v2 §6, §10): the status words and their tones, how a source
// chip names its place, numbers as a person reads them, and the products' series colours. The room itself is the API's
// generated model (`DataRoomView`); nothing here computes a science number.

import type { Schema } from "@/lib/api";

export type Room = Schema<"DataRoomView">;
export type Value = Schema<"Value">;
export type Chip = Schema<"Chip">;
export type Status = Value["status"];
export type Section = Schema<"Section">;
export type Study = Schema<"RoomStudy">;
export type Dissolution = Schema<"DissolutionView">;
export type Decision = Schema<"RoomDecision">;
export type DataRequest = Schema<"DataRequest">;
export type InputRow = Schema<"InputRow">;
export type FileView = Schema<"FileView">;
export type Problem = Schema<"Problem">;
export type Run = Schema<"RoomRun">;
export type Requirements = Schema<"Requirements">;
export type RequirementItem = Schema<"RequirementItem">;
export type Publication = Schema<"RoomPublication">;
/** The question card with every field filled (the contract leaves a field with a default optional). */
export type QuestionCard = Required<Schema<"QuestionCard">>;

export function fullCard(card: Schema<"QuestionCard">): QuestionCard {
  return { question: card.question, regulator: card.regulator ?? "", approach: card.approach ?? "",
           context_of_use: card.context_of_use ?? "", products: card.products ?? [], checklist: card.checklist ?? [],
           quotes: card.quotes ?? [] };
}

/** The status words of plan §6, each with its tone (a class) and its meaning (a hover title). */
export const STATUS: Record<Status, { word: string; means: string }> = {
  verified: { word: "Verified", means: "two independent sources agree, or our recomputation reproduces the client's number" },
  sponsor: { word: "Sponsor data", means: "from the client's own reports or data, one source" },
  literature: { word: "Literature", means: "from a publication, a label or a database" },
  calculated: { word: "Calculated", means: "computed by the platform from verified inputs; the rule is shown" },
  entered: { word: "Entered", means: "entered by a person, with a reason" },
  conflict: { word: "Conflict", means: "sources disagree beyond tolerance; both are shown" },
  missing: { word: "Missing", means: "needed and not found; a data request exists" },
};

// the four status words of Inputs where they fit (decision G1-1: Inputs' rules apply to both pages; the console
// redesign, slice 4a): a section in order is Done, one with something to check is To confirm, one that lacks data is
// Missing; a section with nothing delivered yet keeps its own words, as it is no task yet
export const SECTION_STATE: Record<Section["status"], string> = {
  ok: "Done", attention: "To confirm", missing: "Missing", empty: "Nothing yet",
};

export const AREA: Record<DataRequest["area"], string> = {
  A: "Formulation and manufacturing", B: "In vitro", C: "Drug substance and disposition", D: "Clinical",
};

/** Which data requests each section ends with (plan §5: "data requests at the bottom"). */
export const SECTION_AREA: Partial<Record<string, DataRequest["area"]>> = {
  substance: "C", adme: "C", formulation: "A", solubility: "B", dissolution: "B", clinical: "D", observed: "D",
};

export const BLOCK: Record<InputRow["block"], string> = {
  compound: "Compound", formulation: "Formulation", individual: "Individual and population", protocol: "Protocol",
  event: "Events", observed: "Observed data", target: "Evaluation targets",
};

export const PURPOSE: Record<string, string> = { used: "Used", context: "Context", not_needed: "Not needed" };

export const REQUEST_STATUS: Record<DataRequest["status"], string> = { open: "Open", not_needed: "Not needed", answered: "Answered" };

export const METRIC: Record<string, string> = { cmax: "Cmax", tmax: "Tmax", auc_t: "AUC0–t", auc_inf: "AUC0–∞" };
export const STATISTIC: Record<string, string> = {
  geometric_mean: "geometric mean", arithmetic_mean: "arithmetic mean", median: "median",
};

// a fact's field as the room's tables name it (the engine keeps the agents' vocabulary, which describes rather than names)
const PROPERTY: Record<string, string> = {
  "substance.mw": "Molecular weight", "substance.salt": "Salt form", "substance.dose_basis": "Dose basis", "substance.pka": "pKa",
  "substance.logp": "log P", "substance.logd": "log D", "substance.solubility": "Solubility", "substance.particle_size": "Particle size",
  "substance.solid_form": "Solid form", "substance.melting_point": "Melting point", "substance.permeability": "Permeability",
  "substance.bcs": "BCS class", "adme.fu": "Protein binding", "adme.bp_ratio": "Blood-to-plasma ratio",
  "adme.vd": "Volume of distribution", "adme.cl": "Clearance", "adme.bioavailability": "Absolute bioavailability",
  "adme.tmax": "Tmax", "adme.half_life": "Half-life", "adme.metabolism": "Metabolism", "adme.excretion": "Excretion",
  "adme.food_effect": "Food effect", "adme.ddi": "Interactions", "adme.transporters": "Transporters",
  "product.name": "Product", "product.role": "Role", "product.strength": "Strength", "product.dosage_form": "Dosage form",
  "product.release": "Release", "product.manufacturer": "Manufacturer", "product.batch": "Batch", "product.coating": "Coating",
  "product.core_weight": "Core weight", "product.composition_change": "What changed", "batch.use": "Batch use",
  "batch.api_batch": "Drug-substance batch", "study.id": "Study", "study.title": "Title", "study.design": "Design",
  "study.blinding": "Blinding", "study.n_planned": "Subjects planned", "study.n_dosed": "Subjects dosed",
  "study.n_completed": "Subjects completed", "study.completed_subjects": "Completed (as listed)",
  "study.statistical_set": "Statistical set (as listed)", "study.excluded_subjects": "Withdrawn or excluded",
  "study.population": "Population", "study.sex": "Sex", "study.ethnicity": "Ethnicity", "study.age": "Age", "study.weight": "Weight",
  "study.height": "Height", "study.bmi": "BMI", "study.dose": "Dose", "study.route": "Route", "study.regimen": "Regimen",
  "study.fasting": "Fasting", "study.fed": "Fed", "study.meal_times": "Meals after the dose", "study.meal_composition": "Meal",
  "study.water": "Water with the dose", "study.comedication": "Co-medication", "study.washout": "Washout",
  "study.sampling_times": "Sampling times", "study.analyte": "Analyte", "study.matrix": "Matrix", "study.lloq": "LLOQ",
  "study.bioanalytical_method": "Bioanalysis", "study.be_result": "Bioequivalence result", "study.dates": "Dosing dates",
};

const capital = (text: string) => (text ? text[0].toUpperCase() + text.slice(1) : text);

/** A value's property as a table names it. */
export function propertyOf(v: Value): string {
  const field = v.key.split("[")[0];
  return PROPERTY[field] ?? capital(v.label);
}

/** The file's own name (the last part of its path in the delivery). */
export const baseName = (path: string) => path.split("/").pop() ?? path;

/** Where a chip points, short: "p. 3, line 12", "C2", "line 4". */
export function placeOf(chip: Chip): string {
  const page = /^p(\d+)$/.exec(chip.part);
  if (page) return `p. ${page[1]}, line ${chip.line}`;
  if (chip.part.startsWith("sheet:")) return chip.ref || `line ${chip.line}`;
  return `line ${chip.line}`;
}

/** A chip as a person reads it: the file's name and the place. */
export const chipLabel = (chip: Chip) => `${baseName(chip.file)} · ${placeOf(chip)}`;

/** A chip written out in full, for paper (plan §5 step 8: chips cannot be clicked there). */
export function chipText(chip: Chip): string {
  const sheet = chip.part.startsWith("sheet:") ? ` (sheet ${chip.part.slice(6)})` : "";
  return `${baseName(chip.file)}${sheet} · ${placeOf(chip)}`;
}

/** The rules' label as a person reads it: "Data room rules 0.1 (UNVERIFIED)", with their fingerprint when `full`. */
export function rulesLabel(rules: string, full = false): string {
  const [label, sha] = rules.split(" sha256:");
  const named = label.replace(/^dataroom_rules/, "Data room rules");
  return full && sha ? `${named} · sha256 ${sha}` : named;
}

/** A number as a person reads it: four significant figures at most, no trailing zeros. */
export function num(x: number | null | undefined, digits = 4): string {
  if (x === null || x === undefined || !Number.isFinite(x)) return "—";
  if (Number.isInteger(x) && Math.abs(x) < 1e6) return String(x);
  const abs = Math.abs(x);
  const text = abs >= 1e5 || abs < 1e-3 ? x.toExponential(2) : String(Number(x.toPrecision(digits)));
  return text;
}

/** A value with its unit. */
export function valueText(value: number | string | null | undefined, unit?: string | null): string {
  if (value === null || value === undefined || value === "") return "—";
  const v = typeof value === "number" ? num(value) : value;
  return unit ? `${v} ${unit}` : v;
}

/** The series colour of a product's role (plan §10: reference indigo, test teal, reformulated magenta). */
export function roleColour(role: string | null | undefined): string {
  if (role === "reference") return "var(--series-ref)";
  if (role === "test" || role === "original") return "var(--series-test)";
  if (role === "reformulated") return "var(--series-reform)";
  return "var(--ink-dim)";
}

/** A role's colour as a hex value (for the charts, which do not read CSS variables). */
export function roleHex(role: string | null | undefined): string {
  if (role === "reference") return "#4B2A99";
  if (role === "test" || role === "original") return "#1A9AA6";
  if (role === "reformulated") return "#C2307A";
  return "#6e6e73";
}

/** A product's role on the question card ("" when the card does not name it). */
export function roleOf(room: Room, product: string): string {
  return room.question?.products?.find((p) => p.name === product)?.role ?? "";
}

/** A date as "22 Nov 2026, 09:14" (the audit keeps the instant; the page shows it plainly). */
export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** The numbers written in a text ("4 h and 10 h" → 4, 10): where a meal is marked on a chart. */
export const numbersIn = (text: string) => (text.match(/\d+(?:\.\d+)?/g) ?? []).map(Number);

/** Every conflict the room holds: a value whose sources disagree, and a client number our recomputation does not give. */
export function conflicts(room: Room): { label: string; detail: string; chips: Chip[] }[] {
  const out: { label: string; detail: string; chips: Chip[] }[] = [];
  const values = [...room.substance, ...room.adme, ...room.products, ...room.studies.flatMap((s) => s.facts)];
  for (const v of values.filter((x) => x.status === "conflict")) {
    out.push({ label: propertyOf(v), detail: [v, ...v.others].map((o) => valueText(o.value, o.unit)).join(" vs "),
               chips: [...v.sources, ...v.others.flatMap((o) => o.sources)] });
  }
  const differs = new Set(["NCA_DIFFERS", "MEAN_ROW_DIFFERS", "RSD_ROW_DIFFERS", "COMPLETERS_DIFFER", "DOSED_DIFFERS"]);
  for (const s of room.studies) {
    for (const p of s.problems.filter((x) => differs.has(x.code))) out.push({ label: s.study_id, detail: p.message, chips: p.where ? [p.where] : [] });
  }
  for (const d of room.dissolution) {
    for (const p of d.problems.filter((x) => differs.has(x.code))) {
      out.push({ label: `Dissolution ${d.batch}, ${d.medium}`, detail: p.message, chips: p.where ? [p.where] : [] });
    }
  }
  return out;
}
