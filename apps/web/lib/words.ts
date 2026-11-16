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

/** Where To do's "Ask the client" lists the release of a tablet study's product (the client request's line for the
 *  data plan's REQ-form.release: `study_requirements.unnamed_product_items` when no product is here). */
export const ASK_FORMULATION = "todo-ask-REQ-form.release";
/** Another way to settle a check than its area: what the link says, the area it opens and what it opens there
 *  (`query`, added to the area's URL: `add=product` opens the form that adds a product, `release=<product>` the
 *  product's card at its release, `at=<place>` brings a place of the area into view). */
export type Way = { say: string; area: Tab; query?: string };
/** A way with the name of its area, and what it is (the page's tests name the link by it): `release` uses a product's
 *  dissolution profile as its release, `dissolution` adds a product's dissolution data, `add` adds a product, `ask` asks
 *  the client, `choose` chooses the formulation a study used. */
export type WayLink = Way & { id: "release" | "dissolution" | "add" | "ask" | "choose"; name: string };
/** A readiness check in words, keyed by its raw name without the reference in brackets ("S0 completeness (MS-01
 *  §2.2)" is keyed "S0 completeness"); `waiting` says what is open in a few words, `fix` what a person does and where,
 *  `area` the area of Inputs where that is done (a link from the step bar, Run and Review & sign: final review OWN-13).
 *  A tablet study's formulation has more ways than its area, which follow what the project holds (`formulationWays`). */
const CHECKS: Record<string, { label: string; waiting: string; fix: string; area: Tab }> = {
  "assembly": { label: "Inputs put together", waiting: "the inputs could not be put together",
                fix: "Put together from every source; a problem names its source.", area: "todo" },
  "S0 completeness": { label: "Minimum compound data", waiting: "compound values missing",
                       fix: "Fill them in under To do, “Fill in what's missing”, or on Compound.", area: "todo" },
  "every pathway placeable": { label: "Each elimination pathway maps to a PK-Sim process", waiting: "an elimination pathway has no PK-Sim process",
                               fix: "Choose its process on Compound.", area: "compound" },
  "expression profiles": { label: "Enzyme and transporter expression", waiting: "enzyme or transporter expression missing",
                           fix: "Set on Populations and individuals.", area: "individuals" },
  "formulations of solid studies": { label: "A formulation for each tablet study", waiting: "a tablet study has no formulation",
                                     fix: "To do's formulation item says what each tablet study lacks; it is settled on Products and dissolution.",
                                     area: "formulations" },
  "multiple-dose regimens": { label: "Dosing of multiple-dose studies", waiting: "the dosing of a multiple-dose study is missing",
                              fix: "Fill it in on its study, on Clinical studies.", area: "studies" },
  "demographics stated": { label: "Demographics of confirmed studies", waiting: "the demographics of a study are missing",
                           fix: "Enter them on Populations and individuals, or ask the client.", area: "individuals" },
  "observed data to judge on": { label: "Observed data to compare the model with", waiting: "no observed data confirmed yet",
                                 fix: "Confirm a study's data on Clinical studies, or add data.", area: "studies" },
  "observed data are real": { label: "Observed data are real, not test data", waiting: "some observed data are test data",
                              fix: "Leave the test data out on Clinical studies.", area: "studies" },
  "every planned simulation builds": { label: "All planned simulations build", waiting: "the model can't be built yet",
                                       fix: "Follows once the values above are in.", area: "todo" },
};
const checkKey = (raw: string) => raw.replace(/\s*\([^)]*\)\s*$/, "");

/** A model check's label in words ("Minimum compound data (6 missing)" with its detail's count). */
export function checkLabel(raw: string, detail: string[] = [], ok = true): string {
  const known = CHECKS[checkKey(raw)];
  if (!known) return spaced(raw);
  return !ok && checkKey(raw) === "S0 completeness" && detail.length ? `${known.label} (${detail.length} missing)` : known.label;
}
/** What gives a tablet study its formulation as the project stands (the API's `FormulationWayView`, on the Inputs step
 *  and on To do's formulation item: `modeler_project.formulation_way`): use a product's dissolution profile as its release
 *  (`products`: those whose profile can), add a product's dissolution data (`products`: those here), add a product (none
 *  is here) or choose the formulation a study used (several are in the model). */
export type FormulationWay = {
  way: "use_profile" | "add_dissolution" | "add_product" | "choose"; products: string[]; studies: string[];
  /** use_profile: the first product's profile can be used now; false: its product's dissolution data are confirmed first */
  ready?: boolean;
};
const FORMULATIONS = "formulations of solid studies";
/** Names said as one choice: "A", "A or B", "A, B or C". */
const either = (names: string[]) => (names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} or ${names[names.length - 1]}`);
/** Names said together: "A", "A and B", "A, B and C". */
const both = (names: string[]) => (names.length < 2 ? names.join("") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`);
/** What no product here says of a tablet study's formulation (round 3, owner-job gap 11): the lever is the product, added
 *  on Products and dissolution, or the client, asked under "Ask the client". */
export const NO_PRODUCT = "No product is here to give it a release: add the product the study used (“Add a product”, on Products and "
  + "dissolution) with its dissolution data, or ask the client for them (“Ask the client”, on To do).";
/** The ways to give a tablet study its formulation, as the project stands (final review round 4: "add a product" was
 *  named whatever the project held, and opened an empty form where products with dissolution profiles were here): what
 *  the step bar says is open (`waiting`), the situation in a few words (`situation`, said before the ways where they are
 *  links), a sentence where no link can be (`fix`) and the ways, each a link. One source for the step bar, Review & sign
 *  and Run, To do's formulation item and Products and dissolution. Without a way (none fits: a formulation not complete,
 *  of a type the builder does not place), only the area. */
export function formulationWays(w: FormulationWay | null | undefined): { waiting: string; situation: string; fix: string; ways: WayLink[] } {
  const link = (id: WayLink["id"], say: string, area: Tab, query?: string): WayLink => ({ id, say, area, query, name: AREA_NAME[area] });
  const ask = link("ask", "ask the client", "todo", `at=${ASK_FORMULATION}`);
  const products = w?.products ?? [];
  const card = `release=${encodeURIComponent(products[0] ?? "")}`;
  const waiting = CHECKS[FORMULATIONS].waiting;
  switch (w?.way) {
    case "use_profile":
      // its product's dissolution data not confirmed yet: confirmed first, then the profile is used (the API refuses it
      // before), said as the order it is done in
      if (w.ready === false && products.length) {
        return {
          waiting,
          situation: products.length === 1 ? `the dissolution profile of ${products[0]} is here, its data to confirm first`
            : `the dissolution profiles of ${both(products)} are here, their data to confirm first`,
          fix: `Confirm the dissolution data of ${products[0]} on its card (“Confirm”), then use its profile as its release (“Use this profile `
            + `as the release”), on Products and dissolution${products.length > 1 ? ` (or the profile of ${either(products.slice(1))})` : ""}.`,
          ways: [link("release", "confirm a product's dissolution data, then use its profile as its release", "formulations", card)],
        };
      }
      return {
        waiting,
        situation: products.length === 1 ? `the dissolution profile of ${products[0]} is here`
          : products.length ? `the dissolution profiles of ${both(products)} are here` : "a dissolution profile is here",
        fix: products.length === 1
          ? `Use the dissolution profile of ${products[0]} as its release: “Use this profile as the release” on its card, on Products and dissolution.`
          : products.length
            ? `Use a product's dissolution profile as its release: “Use this profile as the release” on its card, on Products and dissolution (${either(products)}).`
            : "Use a dissolution profile as its release: “Use as release” under the profiles of no product, on Products and dissolution.",
        ways: [link("release", "use a product's dissolution profile as its release", "formulations", card)],
      };
    case "add_dissolution":
      return {
        waiting, situation: "no product here has a dissolution profile that can give a release",
        fix: `No product here has a dissolution profile that can give a release: add the dissolution file of ${either(products) || "the product"} `
          + "(Add data), or ask the client for it (“Ask the client”, on To do).",
        ways: [link("dissolution", "add a product's dissolution data", "formulations", card), ask],
      };
    case "add_product":
      return { waiting, situation: "no product is here", fix: NO_PRODUCT, ways: [link("add", "add a product", "formulations", "add=product"), ask] };
    case "choose":
      return {
        waiting: "a tablet study does not say which formulation it used", situation: "several formulations are in the model",
        fix: "Several formulations are in the model and a tablet study names none: choose the one it used, on Products and dissolution.",
        ways: [link("choose", "choose the formulation it used", "formulations",
                    w.studies[0] ? `at=${encodeURIComponent(`formulation-${w.studies[0]}`)}` : undefined)],
      };
    default:
      return { waiting, situation: "", fix: CHECKS[FORMULATIONS].fix, ways: [] };
  }
}
/** Where an open check is settled, in a sentence (a tablet study's formulation: as the project stands, `formulationWays`). */
export const checkFix = (raw: string, formulation?: FormulationWay | null) =>
  checkKey(raw) === FORMULATIONS ? formulationWays(formulation).fix : CHECKS[checkKey(raw)]?.fix ?? "";
/** A reason the step bar gives for Inputs (a raw check name, or the step's own sentence), in plain words. */
export const stepReason = (raw: string, formulation?: FormulationWay | null) =>
  checkKey(raw) === FORMULATIONS ? formulationWays(formulation).waiting : CHECKS[checkKey(raw)]?.waiting ?? raw;
/** Why the plan cannot read the inputs yet (`modeler_project.inputs.inputs_ready`, the plan route's 409), in words: each
 *  failing check in the step bar's words, never its raw name or its reference (final review round 3, OWN-8: Review &
 *  sign printed "S0 completeness (MS-01 §2.2); formulations of solid studies; …" under the list that names them). */
export function readinessText(raw: string): string {
  const text = raw.trim();
  const failing = /^the model inputs are not ready: (.+)$/i.exec(text);
  if (failing) {
    const said = failing[1].split("; ").map((c) => CHECKS[checkKey(c)]?.waiting ?? spaced(checkKey(c)));
    return `The model inputs are not ready: ${said.join("; ")}.`;
  }
  if (/^the model inputs are not assembled yet$/i.test(text)) return "The model inputs have not been put together yet: Inputs puts them together when it opens.";
  if (/^the model inputs changed since they were checked/i.test(text)) return "The model inputs changed since they were last checked: Inputs checks them again when it opens.";
  if (/^the inputs have no CPF or no study$/i.test(text)) return "The inputs hold no compound values or no study yet.";
  return text;
}
/** Where on Inputs a reason the step bar gives is settled (`?tab=`), with the other ways where there are (a tablet
 *  study's formulation: those that fit what the project holds, `formulation` as the API reads it, `formulationWays`):
 *  null for a reason that is not a model check (the step's own sentence). */
export function stepWhere(raw: string, formulation?: FormulationWay | null): {
  area: Tab; name: string; waiting: string; situation: string; fix: string; ways: WayLink[];
} | null {
  const known = CHECKS[checkKey(raw)];
  if (!known) return null;
  if (checkKey(raw) === FORMULATIONS) return { area: known.area, name: AREA_NAME[known.area], ...formulationWays(formulation) };
  return { area: known.area, name: AREA_NAME[known.area], waiting: known.waiting, situation: "", fix: known.fix, ways: [] };
}
/** The URL of an area of Inputs, or of another way to settle a check there (`?tab=<area>&<query>`). */
export const inputsHref = (projectId: string, way: Pick<Way, "area" | "query">) =>
  `/projects/${encodeURIComponent(projectId)}/inputs?tab=${way.area}${way.query ? `&${way.query}` : ""}`;

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
  // the elimination pathways a value is filed under (modeler_project.inputs.PATHWAY_TARGETS; final review OWN-5)
  "elim.hepatic.total.plasma_clearance": "Hepatic plasma clearance (total)", "elim.hepatic.total_cl": "Hepatic plasma clearance (total)",
  "elim.renal.total.plasma_clearance": "Renal plasma clearance (total)",
};
/** A model input of a family, named by what its id says (the enzyme, the formulation, the pKa group): never by the id. */
const FAMILY_LABEL: [RegExp, (m: RegExpExecArray) => string][] = [
  [/^phys\.pka\.(acid|base)\.(\d+)$/, (m) => `pKa, ${m[1] === "acid" ? "acidic" : "basic"}${Number(m[2]) > 0 ? ` (group ${Number(m[2]) + 1})` : ""}`],
  [/^elim\.hepatic\.([^.]+)\.clspec$/, (m) => `Specific clearance by ${enzyme(m[1])} (CLspec)`],
  [/^elim\.hepatic\.([^.]+)\.cl_intrinsic$/, (m) => `Intrinsic clearance by ${enzyme(m[1])} (CLint)`],
  [/^elim\.hepatic\.([^.]+)\.km$/, (m) => `Km of ${enzyme(m[1])}`],
  [/^elim\.hepatic\.([^.]+)\.vmax$/, (m) => `Vmax of ${enzyme(m[1])}`],
  [/^elim\.fm\.([^.]+)$/, (m) => `Fraction metabolized by ${enzyme(m[1])} (fm)`],
  [/^form\.(.+)\.type$/, (m) => `${m[1]}: release model`],
  [/^form\.(.+)\.weibull\.(t50|shape|lag|suspension)$/, (m) => `${m[1]}: ${FORM_PART[m[2]]}`],
];
const enzyme = (name: string) => (name === "<enzyme>" ? "an enzyme" : name);
/** A Weibull formulation's values (pbpk_domain.cpf.formulations.WEIBULL_PARAMETERS: PK-Sim's harvested names). */
const FORM_PART: Record<string, string> = {
  t50: "Dissolution time (50% dissolved)", shape: "Dissolution shape", lag: "Lag time", suspension: "Use as suspension",
};
export const paramLabel = (id: string) => {
  if (PARAM_LABEL[id]) return PARAM_LABEL[id];
  for (const [rule, say] of FAMILY_LABEL) { const m = rule.exec(id); if (m) return say(m); }
  return id;
};
/** Every model input's id inside a sentence (a check's or a flag's own words), said by its label; a sentence that is
 *  one id ("elim") is said by that id's label. */
export const idWords = (text: string) => {
  const lower = (label: string) => (/^[A-Z][a-z]/.test(label) ? label.charAt(0).toLowerCase() + label.slice(1) : label);
  if (PARAM_LABEL[text.trim()]) return lower(PARAM_LABEL[text.trim()]);
  return text.replace(/\b(?:phys|bind|elim|perm|dist)\.[A-Za-z0-9_<>]+(?:\.[A-Za-z0-9_<>]+)*/g, (id) => {
    const label = paramLabel(id);
    return label === id ? id : lower(label);
  });
};

/** A formulation the model holds, in one line (final review OWN-8): "Test 10 mg · release Weibull · t50 18 min · shape
 *  1.3 · lag 0 min", from its CPF values (`form.<name>.type`, `form.<name>.weibull.*`, as the Inputs rows give them). */
export function formulationLine(name: string, values: Record<string, { value: unknown; unit: string | null }>): string {
  const n = (key: string) => {
    const v = values[key];
    if (!v || v.value === null || v.value === undefined) return null;
    return `${typeof v.value === "number" ? +v.value.toPrecision(3) : String(v.value)}${v.unit ? ` ${v.unit}` : ""}`;
  };
  const type = values.type?.value;
  const parts = [name, type ? `release ${String(type)}` : "release not set"];
  if (n("weibull.t50")) parts.push(`t50 ${n("weibull.t50")}`);
  if (n("weibull.shape")) parts.push(`shape ${n("weibull.shape")}`);
  if (n("weibull.lag")) parts.push(`lag ${n("weibull.lag")}`);
  return parts.join(" · ");
}

/** Why a file is withheld until the plan is signed (D-15), from the blinded studies whose values it holds
 *  (`DocumentView.blinded_by`): it waits whole, its other figures and pages too, as the delivery's rule withholds a file
 *  (round 3: a paper one figure of which was digitized for a blinded study waits with the rest; the owner's decision). */
export function withheldWhy(studies: string[]): string {
  const held = studies.length ? `the values of ${studies.length === 1 ? "study" : "studies"} ${studies.join(", ")}` : "the values of a blinded study";
  return `it holds ${held}, blinded until the plan is signed, and the whole file waits until then, its other figures and pages too`;
}

/** A unit as a person writes it: PK-Sim's "Log Units" of a lipophilicity is a log ratio, written without a unit. */
export const unitText = (unit: string | null | undefined) => (!unit || unit === "Log Units" ? "" : unit);

/** The problems of the formulation item one by one: its own list (`details`, the readiness check's), else its message
 *  split between problems only, never inside one: each problem starts with its study ("CL-01: …"), and a problem may
 *  itself hold "; " ("formulation 'X' is of type 'Y'; the builder places Weibull, …": round 3, the skeptic's risk). */
export function formulationParts(t: { message: string; details?: unknown }): string[] {
  if (Array.isArray(t.details) && t.details.every((d) => typeof d === "string")) return t.details as string[];
  return t.message.split(/; (?=[^;:\s][^;:]*: )/).map((p) => p.trim()).filter(Boolean);
}

/** Why a solid study has no formulation the model can use (the readiness check "formulations of solid studies", from
 *  `pbpk_domain.cpf.formulations`), in words: "CL-01: a tablet or capsule study, and the model holds no formulation". */
export function formulationProblem(text: string): string {
  const said: [RegExp, (m: RegExpExecArray) => string][] = [
    [/^(.+?): the study is a solid oral form but the CPF defines no formulation .*$/,
     (m) => `${m[1]}: a tablet or capsule study, and the model holds no formulation yet`],
    [/^(.+?): the CPF defines no formulation '(.+)' .*$/, (m) => `${m[1]}: the model holds no formulation “${m[2]}”`],
    [/^(.+?): the study does not name its formulation and the CPF defines several: (.+)$/,
     (m) => `${m[1]}: choose which formulation it used (${m[2]})`],
    [/^(.+?): Weibull formulation '(.+)' needs (.+) \(the in-vitro dissolution fit\)$/,
     (m) => `${m[1]}: formulation “${m[2]}” has no ${m[3].split(", ").map((k) => FORM_PART[k.split(".").pop() ?? ""] ?? k).join(", ").toLowerCase()} yet`],
    [/^(.+?): formulation '(.+)' is of type '(.+)'; .*$/, (m) => `${m[1]}: formulation “${m[2]}” is a ${m[3]} release, which the model cannot build yet`],
    [/^(.+?): particle formulation '(.+)' needs .*$/, (m) => `${m[1]}: formulation “${m[2]}” needs its particle thickness and radius`],
    [/^(.+?): binned product '(.+)' needs .*$/, (m) => `${m[1]}: product “${m[2]}” needs its bins and their mass fractions`],
    [/^(.+?): binned product '(.+)': a bin cannot itself be a binned product$/, (m) => `${m[1]}: a bin of product “${m[2]}” is itself a product of bins, which the model cannot build`],
    [/^(.+?): study record: .*$/, (m) => `${m[1]}: its facts are not complete enough to build its simulation (see the study on Clinical studies)`],
  ];
  for (const [rule, say] of said) { const m = rule.exec(text); if (m) return say(m); }
  return idWords(text);
}

/** An open compound item's own sentence (the /inputs to-do's `message`), in words: no evidence ids, no CPF ids, no
 *  engine codes (what a held value's flags say is listed under its source). */
export function todoMessage(kind: string, message: string): string {
  const text = message.replace(/^ev-[0-9a-f]+: /, "");
  if (kind === "review") {
    const held = /^(\S+) = (.+?) is held until a person accepts or corrects it/.exec(text);
    if (held?.[1] === "elim") return `${held[2]} is filed under no elimination pathway: it is used once it is filed under one (below).`;
    if (held) return `${paramLabel(held[1])} = ${held[2].replace(/ Log Units$/, "")} waits for your check before it is used: why is said under its source.`;
  }
  if (kind === "correct") {
    if (/^'elim' means /.test(text)) return "A value filed under no elimination pathway: file it under the pathway it belongs to. Until then it is kept out of the model.";
    if (/is a template; give the concrete parameter$/.test(text)) return "Filed under a kind of parameter, not the parameter itself: choose the parameter it is.";
  }
  if (kind === "pka") {
    const pka = /^pKa (\S+) — the conditions must say acid or base$/.exec(text);
    if (pka) return `pKa ${pka[1]}: its source does not say whether it is acidic or basic.`;
  }
  return idWords(text).replace(/\(kept out of the CPF\)/g, "(kept out of the model)");
}

// --- why a value waits for a check (an evidence item's flags, modeler_project.evidence) -----------------------------

/** The conditions a template writes with a comma and no bracket, one condition each: "fu,inc" (the fraction unbound in
 *  the incubation; `core_small_molecule.yaml` REQ-elim.clint, `app_ddi.yaml`), which the split gives as "fu" · "inc". */
const COMMA_CONDITIONS: [string, string][] = [["fu", "inc"]];
/** A list of conditions as its template writes it: the data plan's template list is read split at every comma, so
 *  "system (HLM, hepatocytes, rCYP)" arrives as "system (HLM" · "hepatocytes" · "rCYP)" and "fu,inc" as "fu" · "inc";
 *  the pieces of one bracket, or of one such condition, are one condition again. A piece whose bracket is not among the
 *  pieces given (the source stated another piece of it) is closed or opened on its own: "system (HLM)", "rCYP", never a
 *  stray bracket; a piece of "fu,inc" alone ("fu" would read as the plasma's fraction unbound, "inc" as nothing) is said
 *  as the whole condition. */
export function bracketed(parts: string[]): string[] {
  const out: string[] = [];
  let depth = 0;
  for (const raw of parts) {
    const part = raw.trim();
    const whole = COMMA_CONDITIONS.find((pair) => pair.includes(part));
    if (depth > 0 && out.length) out[out.length - 1] = `${out[out.length - 1]}, ${part}`;
    else out.push(whole ? whole.join(",") : part);
    depth = Math.max(0, depth + (part.match(/\(/g)?.length ?? 0) - (part.match(/\)/g)?.length ?? 0));
  }
  return [...new Set(out.map((c) => {
    const open = c.match(/\(/g)?.length ?? 0, shut = c.match(/\)/g)?.length ?? 0;
    return open > shut ? `${c})` : shut > open ? c.replace(/\)\s*$/, "") : c;
  }))];
}
const CONDITION = "condition_missing: ";
/** One flag in a person's words (no engine codes, no ids). */
function flagText(flag: string): string {
  const said: [RegExp, (m: RegExpExecArray) => string][] = [
    [/^needs_conversion: no storage unit known for elim; .*$/, () => "Filed under no elimination pathway: choose the pathway it belongs to"],
    [/^needs_conversion: no storage unit known for (\S+); .*$/, (m) => `No unit is known for ${idWords(m[1])}: type its value in PK-Sim's unit`],
    [/^needs_conversion: cannot convert '([^']*)' to (\S+) for .*$/, (m) => `Not converted: ${m[1] || "no unit"} does not convert to ${m[2]}`],
    [/^needs_conversion: an absolute clearance needs the body weight .*$/, () => "Not converted: an absolute clearance needs the body weight to become ml/min/kg"],
    [/^needs_conversion: (\S+) is dimensionless; the stated unit '([^']*)' is unexpected$/, (m) => `Not converted: ${idWords(m[1])} has no unit, but the source states ${m[2]}`],
    [/^needs_conversion: CLint → CLspec is .*$/, () => "Not converted: an intrinsic clearance becomes a specific clearance only by scaling (system, protein, fu,inc), not by a unit change"],
    [/^needs_conversion: (.*)$/, (m) => `Not converted to PK-Sim's unit: ${idWords(m[1])}`],
    [/^value_not_in_quote$/, () => "The value is not in the quoted sentence"],
    [/^species_mismatch: (.*)$/, (m) => `Measured in ${m[1]}, not in humans`],
    [/^outside_physical_range (.*)$/, (m) => `Outside the physically possible range (${m[1]})`],
    [/^conflict >(\S+)-fold with .*$/, (m) => `More than ${m[1]}-fold from another source's value`],
    [/^unconfirmed: (.*)$/, (m) => `Not confirmed yet: ${m[1]}`],
    [/^refiled: from ([^;]+);.*$/, (m) => `Filed under a new parameter (it was filed as ${idWords(m[1])}): check the converted value before you accept it`],
    [/^(?:check|statement|source): (.*)$/, (m) => idWords(m[1])],
  ];
  for (const [rule, say] of said) {
    const m = rule.exec(flag);
    if (m) { const text = say(m); return text.charAt(0).toUpperCase() + text.slice(1); }
  }
  return spaced(flag);
}
/** Why a value waits for a check, one line each, in a person's words (final review OWN-5): the conditions its source does
 *  not state are said once, each as the template writes it ("system (HLM, hepatocytes, rCYP)", not split at its commas). */
export function flagLines(flags: string[]): string[] {
  const conditions = bracketed(flags.filter((f) => f.startsWith(CONDITION)).map((f) => f.slice(CONDITION.length)));
  const out: string[] = [];
  let said = false;
  for (const f of flags) {
    if (!f.startsWith(CONDITION)) out.push(flagText(f));
    else if (!said) { said = true; out.push(`The source does not state: ${conditions.join("; ")}`); }
  }
  return [...new Set(out)];
}

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

/** The values of a unit class (the intake's `UnitClass`, modeler_intake.fields), as a person names them. */
const UNIT_CLASS_WORD: Record<string, string> = {
  mass: "amounts", concentration: "concentrations", time: "times", percentage: "percentages", ratio: "ratios",
  other: "values", none: "values",
};
/** Why the spot check drew a value it sampled (the draw's stratum, the intake rules' `spot_check.strata` as
 *  "table_kind=pk_individual|unit_class=concentration|blq_form=BLQ|cross_file=yes"), in words (final review OWN-8): "picked
 *  at random among the concentrations of individual PK tables, those written “BLQ”, read from another file". */
export function spotGroupText(stratum: string): string {
  const parts = Object.fromEntries(stratum.split("|").map((p) => p.split("=")).filter(([, v]) => v !== undefined)) as Record<string, string>;
  const what = UNIT_CLASS_WORD[parts.unit_class ?? ""] ?? (parts.unit_class ? spaced(parts.unit_class) : "values");
  const where = parts.table_kind === "fact" ? "of the facts read from the files"
    : parts.table_kind ? `of ${tableKindText(parts.table_kind).replace(/ table$/, " tables")}` : "";
  const more = [parts.blq_form ? `those written “${parts.blq_form.replace(/x/g, "…")}”` : "",
                parts.cross_file === "yes" ? "read from another file than the study's own" : ""].filter(Boolean);
  return `picked at random among the ${what}${where ? ` ${where}` : ""}${more.length ? `, ${more.join(", ")}` : ""}`;
}

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

/** A dataset's source locator as the sheet form writes it ("Studies!A2:AK2; PK_Summary!2:7"), in plain words: "sheet
 *  Studies, cells A2 to AK2; sheet PK_Summary, rows 2 to 7"; a sheet named by the reading's recipe ("Fed (recipe
 *  file-…-r1 v1)") as "sheet Fed". A part in the intake grammar is said as `placeText` says it; any other part is given
 *  as it is. */
export function locatorText(locator: string): string {
  // the sheet form's reading of a sheet is named by its recipe ("Fed (recipe file-…-r1 v1)"): the sheet is what a person reads
  return locator.split(";").map((raw) => raw.trim()).filter(Boolean).map((raw) => {
    const recipe = /\(recipe [^)]*\)/.test(raw);
    const part = raw.replace(/\s*\(recipe [^)]*\)/g, "").trim();
    const cells = /^'?((?:[^'!]|'')+?)'?!\$?([A-Z]{1,3})\$?([0-9]+)(?::\$?([A-Z]{1,3})\$?([0-9]+))?$/.exec(part);
    if (cells) {
      const [, sheet, c0, r0, c1, r1] = cells;
      return c1 ? `sheet ${sheet}, cells ${c0}${r0} to ${c1}${r1}` : `sheet ${sheet}, cell ${c0}${r0}`;
    }
    const rows = /^'?((?:[^'!]|'')+?)'?!([0-9]+)(?::([0-9]+))?$/.exec(part);
    if (rows) return rows[3] && rows[3] !== rows[2] ? `sheet ${rows[1]}, rows ${rows[2]} to ${rows[3]}` : `sheet ${rows[1]}, row ${rows[2]}`;
    const place = placeText(part);
    return recipe && place === part ? `sheet ${part}` : place;
  }).join("; ");
}

/** What the loading leaves out of the model (a card's `held`, as the landing writes it), in a person's words: the
 *  fields named by their labels, the engine's terms and check codes dropped ("product attributes (dosage_form,
 *  polymorph): kept in the ledger; only dissolution lands" → "Kept, not used by the model: dosage form, polymorph (only
 *  the dissolution is loaded)"). `own`: the card's own name, not said again at the start of a line. */
export function heldText(line: string, own?: string): string {
  const fields = (list: string) => list.split(",").map((f) => fieldInText(f.trim())).join(", ");
  let text = own && line.startsWith(`${own}: `) ? line.slice(own.length + 2) : line;
  text = text
    .replace(/^demographics the individual does not carry \(([^)]+)\): kept in the ledger; .*$/,
             (_m, l: string) => `Kept, not used by the model: ${fields(l)} (the study's individual is one sex and one PK-Sim population, chosen by a person)`)
    .replace(/^demographics not yet the study's individual \(([^)]+)\): kept in the ledger; the individual (?:needs ([\w, ]+?)|cannot be set)(?: \((.*)\))?$/,
             (_m, l: string, needs: string | undefined, why: string | undefined) =>
               `Kept, not used by the model yet: ${fields(l)} (${individualNeeds(needs ? needs.split(",").map((f) => f.trim()) : [], why ?? "")})`)
    .replace(/^product attributes \(([^)]+)\): kept in the ledger; only dissolution lands$/, (_m, l: string) => `Kept, not used by the model: ${fields(l)} (only the dissolution is loaded)`)
    .replace(/^study facts with no place in the study record \(([^)]+)\): kept in the ledger$/, (_m, l: string) => `Kept, not used by the model: ${fields(l)} (the study record has no place for them)`)
    .replace(/\b(excretion|relations) \(([^)]+)\): kept in the ledger; the model inputs have no place for (?:it|them) yet/,
             (_m, what: string, l: string) => `${what === "excretion" ? "Excretion" : "Drug interactions"} (${fields(l)}): kept, not used by the model (no place for ${what === "excretion" ? "it" : "them"} yet)`)
    .replace(/ \([A-Z][A-Z_]+[A-Z]\)/g, "")
    .replace(/kept in the ledger/g, "kept with the delivery").replace(/\bnot landed\b/g, "not loaded").replace(/\(lands PROPOSED\)/g, "(loaded as proposed)")
    .replace(/the client-review card/g, "the sheet form's card");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Why a spot check's values are drawn, from the draw's own reasons (`DeliverySpotValue.reason`; the intake rules
 *  decide how many: SME-governed): "117 values drawn: 4 key facts of the study, 13 computed from other values are always
 *  checked; 100 are a random sample". */
export function drawText(reasons: (string | null)[]): string {
  const n = (test: (r: string) => boolean) => reasons.filter((r): r is string => r !== null && test(r)).length;
  const named: Record<string, string> = {
    "always:field": "key fact[s] of the study", "always:derived": "computed from other values", "always:digitized": "read from a figure",
    "always:cross_file": "read from another file than the study's own", "always:link": "linking two files",
    "always:override": "with a check accepted as is", "always:failed": "that did not match before",
  };
  const said = (k: number, what: string) => what.replace("[s]", k === 1 ? "" : "s");
  const always: [number, string][] = [
    ...Object.entries(named).map(([reason, what]) => { const k = n((r) => r === reason); return [k, said(k, what)] as [number, string]; }),
    [n((r) => r.startsWith("always:") && !named[r]), "named by the intake rules"],
  ];
  const listed = always.filter(([k]) => k > 0);
  const sampled = n((r) => !r.startsWith("always:"));
  const head = `${plural(reasons.length, "value")} drawn`;
  if (!listed.length) return `${head}: a random sample`;
  const one = listed.length === 1 && listed[0][0] === 1;
  return `${head}: ${listed.map(([k, what]) => `${k} ${what}`).join(", ")} ${one ? "is" : "are"} always checked`
    + (sampled ? `; ${sampled} ${sampled === 1 ? "is" : "are"} a random sample` : "");
}

/** What saving a person's entry does to a spot check drawn already, said before Save (final review round 3): what a
 *  person enters is part of what the spot check is drawn from (its subject's digest and its seed), so it is drawn
 *  again. The values always checked are drawn again with their ticks (`DeliverySpotState.always`); the random sample is
 *  drawn anew, and a value it draws again keeps its tick. How many of the sample carry over is known only once it is
 *  drawn (the draw's rule is the intake rules', SME-governed, unchanged). Null when no spot check is drawn, or it is
 *  stale already. "Saving this changes what the spot check was drawn from, so it is drawn again. Of the 117 values
 *  ticked (recorded by dev-user on 15 Nov 2026, 09:42), the 17 always checked keep their ticks; the 100 drawn at random
 *  are drawn anew, and only those drawn again keep theirs." */
export function redrawText(spot: { state: string; drawn: number; always: number; recorded_by: string | null; recorded_at: string | null }): string | null {
  if (spot.state === "none" || spot.state === "stale") return null;
  const lead = "Saving this changes what the spot check was drawn from, so it is drawn again";
  if (spot.recorded_by === null) return `${lead}: ticks not recorded yet are not kept.`;
  const sampled = spot.drawn - spot.always;
  const who = `recorded by ${spot.recorded_by}${spot.recorded_at ? ` on ${whenText(spot.recorded_at)}` : ""}`;
  const kept = spot.always === 0 ? "" : sampled === 0 ? `${spot.always === 1 ? "it is" : "all are"} always checked and keep${spot.always === 1 ? "s its tick" : " their ticks"}`
    : `the ${spot.always} always checked keep${spot.always === 1 ? "s its tick" : " their ticks"}`;
  const anew = sampled === 0 ? "" : spot.always === 0 ? `all were drawn at random: they are drawn anew, and only those drawn again keep their ticks`
    : sampled === 1 ? "the 1 drawn at random is drawn anew, and keeps its tick only if drawn again"
    : `the ${sampled} drawn at random are drawn anew, and only those drawn again keep theirs`;
  return `${lead}. Of the ${plural(spot.drawn, "value")} ticked (${who}), ${[kept, anew].filter(Boolean).join("; ")}.`;
}

/** A check's message in two parts (the intake checks write "<what it is about>: <what is wrong>[; why it matters]"):
 *  `where` ("arm Reference, analyte not stated, matrix plasma") and `gist`, what is wrong in a few words ("the profile
 *  states more than one LLOQ"), engine terms in a person's words. A message with no "what it is about" is its own gist. */
export function checkGist(message: string): { where: string; gist: string } {
  const at = message.indexOf(": ");
  const where = at > 0 ? message.slice(0, at) : "";
  const rest = at > 0 ? message.slice(at + 2) : message;
  const gist = rest.split(/; |: /)[0].trim();
  return { where: engineWords(where), gist: engineWords(gist || rest) };
}

/** What a study's simulated individual still needs (D-29; `DeliveryIndividual.needs` and `why`, the landing's held
 *  line), in words: "the study's individual needs the PK-Sim population and the sex: choose them with the demographics".
 *  The values are named by their field, never by their ids. */
const NEED_WORD: Record<string, string> = { individual_population: "the PK-Sim population", individual_sex: "the sex simulated",
                                            age_mean: "the mean age" };
export function individualNeeds(needs: string[], why: string): string {
  const named = needs.map((f) => NEED_WORD[f] ?? fieldInText(f));
  const list = named.length > 1 ? `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}` : named[0] ?? "";
  const reasons = why.split("; ").filter(Boolean).map((r) => r
    .replace(/^(\w+) \([^)]*\) is written in '([^']*)', not (\w+)$/, (_m, f: string, unit: string, wanted: string) =>
      `${fieldInText(f)} is written in “${unit}”, not ${wanted}`)
    .replace(/^(\w+) \([^)]*\) is not (a number|one of PK-Sim's)$/, (_m, f: string, what: string) => `${fieldInText(f)} is not ${what}`)
    .replace(/^two values of (\w+) are active: choose one$/, (_m, f: string) => `two values of ${fieldInText(f)}: keep one`)
    .replace(/^the individual is refused: .*$/, "a number is out of range"));
  const parts = [list ? `the study's individual needs ${list}` : "", ...reasons].filter(Boolean);
  return `${parts.join("; ")}: give them with the demographics`;
}

/** A study's simulated individual in a line: "European ICRP 2002 · female · 32 y (21 to 45) · 74 kg". */
export function individualText(d: Record<string, unknown>): string {
  const age = d.age_years !== undefined ? `${String(d.age_years)} y${d.age_min !== undefined && d.age_max !== undefined
    ? ` (${String(d.age_min)} to ${String(d.age_max)})` : ""}` : "";
  return [d.population ? valueWord(String(d.population)) : "", d.sex ? valueWord(String(d.sex)).toLowerCase() : "", age,
          d.weight_kg !== undefined ? `${String(d.weight_kg)} kg` : "", d.height_cm !== undefined ? `${String(d.height_cm)} cm` : ""]
    .filter(Boolean).join(" · ");
}

/** A fact a study record needs (the intake's field, as a gap's `tag` or a check's "needs <field>" names it), in words:
 *  the sheet form's own labels for the same facts and the landing's "(what the study is for)". */
const FACT_WORD: Record<string, string> = {
  n: "the number of subjects", intended_use: "what the study is for", purpose: "what the study is for", route: "the route",
  dose: "the dose", formulation: "the dosage form", food_state: "fasted or fed",
};
export const factText = (field: string) => FACT_WORD[field] ?? `the ${spaced(field)}`;

/** Why a card cannot be loaded yet (its `landing_problem`, the landing's "230-23: the study record needs n, which no
 *  active value states: enter it; …"), in words: "the number of subjects is not stated; the route is not stated". `own`:
 *  the card's own name, not said again. A part the landing words otherwise is given with its engine terms replaced. */
export function landingText(text: string, own?: string): string {
  return text.split("; ").map((part) => {
    const p = own && part.startsWith(`${own}: `) ? part.slice(own.length + 2) : part;
    const need = /^the study record needs (\w+), which no active value states(?: \([^)]*\))?: enter it$/.exec(p);
    return need ? `${factText(need[1])} is not stated` : engineWords(p);
  }).join("; ");
}

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
  individual_population: "PK-Sim population", individual_sex: "Sex simulated",
  product_role: "Role", strength_mg: "Strength (mg)", dosage_form: "Dosage form", release: "Release", batch: "Batch",
  particle_size_d50_um: "Particle size d50 (µm)", polymorph: "Polymorph", salt_form: "Salt form",
  apparatus: "Apparatus", medium: "Medium", ph: "pH", rpm: "Stirring (rpm)", volume_ml: "Volume (mL)",
  // every other field of the intake vocabulary (`modeler_intake.fields`), so the layout editor names none by its id
  // (gate-todo review); the unit is the one the field's name carries
  reference: "Protocol or report", crossover: "Crossover", special_population: "Special population", species: "Species",
  child_pugh: "Child-Pugh class", egfr: "eGFR", gestational_week: "Week of pregnancy", genotype: "Genotype",
  co_medication: "Co-medication", salt_or_base: "Dose as salt or base", meal_type: "Meal", meal_kcal: "Meal energy (kcal)",
  meal_fat_g: "Meal fat (g)", particle_size_d10_um: "Particle size d10 (µm)", particle_size_d90_um: "Particle size d90 (µm)",
  particle_size_method: "Particle size method", surfactant: "Surfactant", temperature_c: "Temperature (°C)",
  cumulative: "Cumulative", component: "Component",
};
export const fieldLabel = (field: string) => FIELD_LABEL[field] ?? `${spaced(field).charAt(0).toUpperCase()}${spaced(field).slice(1)}`;
/** A fact's label inside a sentence: its first letter in lower case, a name in capitals kept ("PK-Sim population",
 *  "LLOQ"). */
export const fieldInText = (field: string) => {
  const label = fieldLabel(field);
  return /^[A-Z]{2}/.test(label) ? label : label.charAt(0).toLowerCase() + label.slice(1);
};

/** A vocabulary entry in words (the study record's enums, the intake vocabulary's choices and the brief's purposes, as
 *  the API sends them in `study_options` or a field's `choices`); an entry with no word is shown as sent. */
const VALUE_WORD: Record<string, string> = {
  oral: "Oral", iv_bolus: "IV bolus", iv_infusion: "IV infusion", other: "Other",
  solution: "Solution", suspension: "Suspension", ir_tablet: "IR tablet", ir_capsule: "IR capsule", mr: "Modified release",
  fasted: "Fasted", fed: "Fed", SD: "Single dose", MD: "Multiple dose",
  model_building: "Model building", internal_validation: "Internal validation", external_validation: "External validation",
  application_verification: "Application verification", supportive: "Supportive",
  plasma: "Plasma", blood: "Blood", serum: "Serum", urine: "Urine", feces: "Feces",
  healthy: "Healthy", patient: "Patients", MALE: "Male", FEMALE: "Female", TEST: "Test", RLD: "RLD", REFERENCE: "Reference", SOLUTION: "Solution", OTHER: "Other",
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

/** A decision someone made already, as a 409 `CONFLICT` names it (`detail.decided`): who, when, why, and where (a
 *  "not data" decision) or the check (an accept as is). */
type Earlier = { id?: string; by?: string; at?: string; why?: string; where?: string; check_id?: string };

/** The 409 of a decision someone made already, in a person's words (final review INT-11): "dev-user marked sheet
 *  Summary, cell A10 as not data on 15 Nov 2026, 10:21: “a note about re-assays”. Restore it to decide again." Null
 *  when the refusal names no earlier decision (its own words are shown then). */
export function alreadyDecidedText(decided: unknown): string | null {
  if (!Array.isArray(decided) || !decided.length) return null;
  const said = (decided as Earlier[]).map((d) => {
    const why = d.why ? `: “${d.why}”` : "";
    const when = d.at ? ` on ${whenText(d.at)}` : "";
    return d.where !== undefined ? `${d.by ?? "Someone"} marked ${placeText(d.where)} as not data${when}${why}.`
      : `${d.by ?? "Someone"} accepted it as is${when}${why}.`;
  });
  const marked = (decided as Earlier[]).some((d) => d.where !== undefined);
  return `${said.join(" ")} ${marked ? "Restore it to decide again." : "The card is read again to show it."}`;
}

// --- a table's layout, in words (final review OWN-8, OWN-2) ---------------------------------------------------------------
// The layout dialog and the layout form say a layout's fields, roles, rules and findings in these words; the rule ids,
// the patterns and the codes stay in a "technical detail" fold. Each name is the intake vocabulary's
// (`DeliveryMappingVocabulary`, read from `modeler_intake`), never one the web made up.

/** A PK parameter's short name, by the part after `pk.` (the intake's `pk.AUC_last`, `pk.CL/F`). */
const PK_WORD: Record<string, string> = {
  AUC_last: "AUC last", AUC_inf: "AUC inf", Cmax: "Cmax", tmax: "tmax", t_half: "half-life", Ctrough: "Ctrough",
  "CL/F": "CL/F", "Vz/F": "Vz/F",
};
/** A field of the intake vocabulary as a layout names it (the layout form's field choices, a column's field), in words:
 *  "AUC last (PK parameter)", "Cmax ratio, test vs reference", never `pk.AUC_last` or `relation.test_vs_reference.Cmax`. */
export function layoutFieldText(name: string): string {
  const pk = (x: string) => PK_WORD[x] ?? spaced(x);
  let m: RegExpExecArray | null;
  if ((m = /^pk\.(.+)$/.exec(name))) return `${pk(m[1])} (PK parameter)`;
  if ((m = /^relation\.ddi_ratio\.(.+)$/.exec(name))) return `${pk(m[1])} ratio, with vs without the interacting drug`;
  if ((m = /^relation\.test_vs_reference\.(.+)$/.exec(name))) return `${pk(m[1])} ratio, test vs reference`;
  const words: Record<string, string> = {
    "excretion.amount": "Amount excreted", "excretion.fraction": "Fraction excreted (%)", "composition.amount": "Amount in the composition",
    "link.study_id": "Study named for a link to another file", "link.protocol": "Protocol named for a link to another file",
    "link.cross_reference": "Reference to another file", concentration: "Concentration", percent_dissolved: "Percent dissolved",
    study_id: "Study", treatment: "Treatment (arm)", product_role: "Product's role", analyte_role: "Analyte's role",
    molecular_weight: "Molecular weight", subject: "Subject", period: "Period", sequence: "Sequence", occasion: "Occasion",
    vessel: "Vessel", product: "Product", interval_start_h: "Interval start (h)", interval_end_h: "Interval end (h)",
  };
  return words[name] ?? fieldLabel(name);
}
/** A field inside a sentence: "the product's role", "the batch", "the pH", "the Cmax (PK parameter)" (a name keeps its capitals). */
const fieldInSentence = (name: string) => {
  const t = layoutFieldText(name);
  return `the ${/^[A-Z][a-z]/.test(t) && !/^(AUC|Cmax|Ctrough|CL|Vz)/.test(t) ? `${t.charAt(0).toLowerCase()}${t.slice(1)}` : t}`;
};

/** What a column holds (a column's role, `MappingSpec` Role), in words. */
const ROLE_WORD: Record<string, string> = {
  time: "time", time_actual: "actual sampling time", time_unit: "time unit, row by row", value: "values", spread: "spread",
  spread_kind: "kind of spread, row by row", statistic: "statistic, row by row", n: "number of subjects (n)", lloq: "LLOQ",
  blq_flag: "below-LLOQ flag", interval_low: "interval, low end", interval_high: "interval, high end", subject: "subject",
  arm: "arm", period: "period", sequence: "sequence", occasion: "occasion", study: "study", analyte: "analyte", matrix: "matrix",
  product: "product", batch: "batch", vessel: "vessel", other_arm: "the other arm", parameter: "parameter name",
  condition: "a condition", unit: "unit, row by row", ignore: "not data",
};
export const layoutRoleText = (role: string) => ROLE_WORD[role] ?? spaced(role);

/** What a row rule makes of the rows it matches (`RowRule.role`), in words. */
const ROW_ROLE_WORD: Record<string, string> = {
  exclude: "not data (left out)", arithmetic_mean: "arithmetic means", geometric_mean: "geometric means", median: "medians",
  spread: "the spread of the values above", n: "the number of subjects (n)", interval_low: "the interval's low end",
  interval_high: "the interval's high end",
};
export const rowRoleText = (role: string) => ROW_ROLE_WORD[role] ?? spaced(role);

/** Where a table states a thing read once for it (a `Cite`): "its caption", "line 2 of the text above it", "the cell
 *  in row 2, column 3". */
export function citeWords(cite: Record<string, unknown>): string {
  const near: Record<string, string> = { caption: "its caption", above: "the text above it", below: "the text below it" };
  if (typeof cite.near === "string") {
    const line = Number(cite.line ?? 1);
    return `${line > 1 ? `line ${line} of ` : ""}${near[cite.near] ?? spaced(cite.near)}`;
  }
  if (cite.row !== undefined && cite.row !== null) return `the cell in row ${String(cite.row)}, column ${String(cite.column)}`;
  return "the table";
}

/** A fact read once for the whole table (a `Constant`), in a sentence: "The batch is read from its caption." */
export const constantText = (c: { field: string; cite: Record<string, unknown> }) => {
  const f = fieldInSentence(c.field);
  return `${f.charAt(0).toUpperCase()}${f.slice(1)} is read from ${citeWords(c.cite)}.`;
};

/** A row rule (`RowRule`) in a sentence: "Rows whose column 1 reads “Mean” are arithmetic means." `literal`: the words
 *  the rule matches, when its pattern is plain words (else it is a pattern, said in the technical detail). */
export function rowRuleText(r: { column: number; role: string; pattern: string; reason?: string | null }, literal: string | null): string {
  const what = literal !== null ? `reads “${literal}”` : "matches a pattern (technical detail)";
  return `Rows whose column ${r.column} ${what} are ${rowRoleText(r.role)}${r.role === "exclude" && r.reason ? `: ${r.reason}` : ""}.`;
}

/** The words a pattern matches when it is plain words with its special characters escaped ("Mean", "S\\.D\\."), else
 *  null. A row rule's text matches its cell whole, upper or lower case alike. */
export function patternWords(pattern: string): string | null {
  const plain = pattern.replace(/\\(.)/g, "$1");
  return escapePattern(plain) === pattern ? plain : null;
}
/** Plain words as a pattern that matches them as written (a row rule's text typed in the layout form). */
export const escapePattern = (words: string) => words.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** A layout's origin and who made it ("suggested by the template rules", "entered by dev-user"): never the rule's id. */
export const layoutMadeBy = (origin: string, by: string, detail = "") =>
  origin === "person" ? `entered by ${detail || by}` : layoutOrigin(origin);

/** What code found wrong when a layout version is checked on a table (`DeliveryMappingFinding`), in a person's words.
 *  `constants`: the layout's facts read once for the table, which a finding's location names by number. The code and
 *  the location are for the technical detail; a message this does not know is given with its engine words replaced. */
export function layoutFindingText(f: { code: string; location: string; message: string },
                                  constants: { field: string; cite: Record<string, unknown> }[] = []): string {
  const constant = /^constants\[(\d+)\]/.exec(f.location);
  const c = constant ? constants[Number(constant[1])] : undefined;
  const fieldIn = /\(([^)]+)\)\s*$/.exec(f.location)?.[1];
  if (f.code === "CONSTANT_NOT_STATED" && (c || fieldIn)) {
    const what = fieldInSentence(c?.field ?? fieldIn!);
    const where = c ? citeWords(c.cite) : "the text it is read from";
    const many = /reads (\d+) readings/.exec(f.message);
    const said = many && Number(many[1]) === 0 ? "is not stated in" : many ? `is stated ${many[1]} times in` : / as ambiguous /.test(f.message)
      ? "is written ambiguously in" : /at the cite, not/.test(f.message) ? "reads otherwise in" : "is not stated in";
    return `${what.charAt(0).toUpperCase()}${what.slice(1)} ${said} ${where}.`;
  }
  if (f.code === "CONSTANT_NOT_STATED" && f.location === "time_reference") return "When the times are counted from is not stated where the layout says.";
  if (f.code === "UNIT_NOT_STATED" || f.code === "UNIT_NOT_CITED") {
    const unit = /unit '([^']+)'/.exec(f.message)?.[1];
    return `The unit${unit ? ` “${unit}”` : ""} is not written where the layout says.`;
  }
  const text = f.message.replace(/\bthe region\b/g, "the table").replace(/\bregion\b/g, "table").replace(/\bthe cited text\b/g, "the text it is read from")
    .replace(/\(([a-z_]+)\)/g, (_m, k: string) => `(${spaced(k)})`);
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}${/[.!?]$/.test(text) ? "" : "."}`;
}

/** Why a read table's number is not read (`DeliveryUnreadCell.why`, the reading's own rule), in words. */
const UNREAD_WHY: Record<string, string> = {
  "": "no column or row of the layout reads it", unparseable: "not a plain number", time_unparseable: "its time is not a plain number",
  qualifier_twice: "a second spread, n or interval for the same value", lloq_differs: "its LLOQ is not the table's",
  time_unit_conflict: "it writes another time unit than its column",
};
export const unreadWhy = (rule: string) => UNREAD_WHY[rule] ?? spaced(rule);
/** The reasons no table layout can clear: the number is written so that no reading takes it (a single cell could only
 *  be set aside as not data, which waits for the owner's decision). */
export const UNREADABLE = new Set(["unparseable", "time_unparseable"]);

/** The rows of a table's body a sample leaves out (review OWN-15), in words: "Row 6 not shown", "Rows 6 to 20 not
 *  shown", "Rows 6 and 9 to 12 not shown"; "" when every row from `first` to `last` is shown. */
export function rowsLeftOut(first: number, last: number, shown: number[]): string {
  const seen = new Set(shown);
  const runs: [number, number][] = [];
  for (let r = first; r <= last; r += 1) {
    if (seen.has(r)) continue;
    const run = runs[runs.length - 1];
    if (run && run[1] === r - 1) run[1] = r; else runs.push([r, r]);
  }
  if (!runs.length) return "";
  const one = runs.length === 1 && runs[0][0] === runs[0][1];
  const said = runs.map(([a, b]) => (a === b ? `${a}` : `${a} to ${b}`));
  return `${one ? "Row" : "Rows"} ${said.length > 1 ? `${said.slice(0, -1).join(", ")} and ${said[said.length - 1]}` : said[0]} not shown`;
}

/** What approving a layout version changes for one table of its layout (`DeliveryTableMove`: the pipeline would read it
 *  with that version instead of the one it is read with now), in words: "Once version 3 is approved, it is read with
 *  version 3 instead of version 2: no number left unread either way; it no longer reads the product's role." The facts
 *  are named by their labels (an LLOQ read once for the table as "the LLOQ"). */
export function moveText(m: { from_version: number; unread_before: number; unread_after: number; facts_lost: string[]; facts_gained: string[] },
                         version: number): string {
  const n = (k: number) => (k ? plural(k, "number") : "no number");
  const numbers = m.unread_before === m.unread_after ? `${n(m.unread_before)} left unread either way`
    : `${n(m.unread_before)} left unread now, ${m.unread_after ? plural(m.unread_after, "number") : "none"} then`;
  return `Once version ${version} is approved, it is read with version ${version} instead of version ${m.from_version}: ${numbers}`
    + (m.facts_lost.length ? `; it no longer reads ${factsInText(m.facts_lost)}` : "")
    + (m.facts_gained.length ? `; it then also reads ${factsInText(m.facts_gained)}` : "") + ".";
}
/** Facts read once for a whole table, by field, in a sentence: "the product's role and the LLOQ". */
export function factsInText(fields: string[]): string {
  const named = fields.map((f) => (f === "lloq" ? "the LLOQ" : fieldInSentence(f)));
  return named.length > 1 ? `${named.slice(0, -1).join(", ")} and ${named[named.length - 1]}` : named[0] ?? "";
}

/** Findings said inside a sentence ("does not read it: the product's role is not stated in its caption; …"): each in
 *  words, its first letter small and its full stop dropped. */
export const findingsInline = (findings: { code: string; location: string; message: string }[],
                               constants: { field: string; cite: Record<string, unknown> }[] = []) =>
  findings.map((f) => layoutFindingText(f, constants).replace(/\.$/, "")).map((t) => `${t.charAt(0).toLowerCase()}${t.slice(1)}`).join("; ");
