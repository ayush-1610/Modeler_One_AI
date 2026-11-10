"""What code reads for Start from the proposal's own words, for every Start field the intake agent left empty (the owner,
2026-11-06: "making sure everything is there; the user will just see through and only change in case the selection or
pre-fills are way wrong").

The floor under the intake agent (A1), and Start's reading when agents are off. Each draft is DRAFTED, not a value until
a person confirms or changes it, and rests on the sentence it was read from, quoted from its page:
- the question of interest: the proposal's objective sentence ("Objective", "to predict / evaluate / support …");
- the context of use: the sentence saying what the results are for (a submission, a waiver, the label, an agency);
- the applications: by what the proposal names (bioequivalence, food effect, an interaction, children, impairment …);
- the formulation types: the dosage forms it names (an extended-release tablet is modified release; a tablet or capsule
  with no release named is immediate release); a dissolution medium is never read as a solution;
- the routes: oral when the product is taken by mouth or is a tablet or capsule; intravenous when an infusion or bolus is
  named; one scenario per strength the proposal names (the owner, 2026-11-08), each with its dose; fasted or fed when the
  proposal names only one;
- the modality: a biologic the proposal names (an antibody, a protein, a peptide) is a large molecule; a drug PubChem
  gives a structure, or whose product is a tablet or capsule, a small molecule.
Two choices are defaults, said so: a full (whole-body) PBPK model of systemic action, the only model the builder makes
(D-28), unless the proposal speaks of a local site of action. A field a person set, or a document states, is kept.

The drug's disposition (the owner, 2026-11-07: "it still does not fill all"), read from the proposal and, where the
proposal says nothing, from the FDA label code stored at the project's start (`compound_sources`, its pharmacokinetics
section), the source named in each draft's note:
- the BCS class a sentence names ("BCS class I");
- the elimination and transport pathways: the enzymes and transporters named (CYP3A4, UGT1A9, P-gp …; "UGT isoforms"
  with none named is "UGT"), skipping a sentence that says one is not involved, and the kinds the sentences describe
  (metabolism, the drug excreted unchanged in urine, tubular secretion, bile, the gut wall);
- nonlinearity: a sentence of saturation, auto-induction or exposure not proportional to the dose is drafted as stated;
  one of linear, dose-proportional pharmacokinetics is drafted as `LINEAR`, which Start shows as "no" (confirmed, it is
  saved as not applicable: linear PK, no Km or Vmax asked);
- enterohepatic recycling: yes when a sentence says it, no when one denies it.
Drafts are not values: the data checklist reads them only once a person confirms them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from modeler_project.brief import Citation, FieldStatus, ProjectBrief
from modeler_project.brief_ops import agent_set, locked
from modeler_project.documents import DocumentLibrary, document_record

CODE = "code:start-reading"
NOTE = "read by code from the proposal's words (the intake agent left it empty): {why}"
_SENTENCE = re.compile(r"[^.!?\n]{20,600}[.!?]?")
_MEDIUM = re.compile(r"dissolution|medium|media|buffer|vessel|USP", re.IGNORECASE)
_MR = re.compile(r"extended[- ]release|modified[- ]release|prolonged[- ]release|controlled[- ]release|sustained[- ]release|"
                 r"delayed[- ]release|\b(?:ER|XR|SR|CR|MR|XL|PR)\b", re.IGNORECASE)
FORMS: tuple[tuple[str, re.Pattern[str], bool], ...] = (       # (option, pattern, never in a dissolution sentence)
    ("suspension", re.compile(r"\bsuspensions?\b", re.IGNORECASE), True),
    ("solution", re.compile(r"\b(?:oral |drinking |intravenous |infusion )?solutions?\b", re.IGNORECASE), True),
    ("ir_tablet", re.compile(r"\btablets?\b", re.IGNORECASE), False),
    ("ir_capsule", re.compile(r"\bcapsules?\b", re.IGNORECASE), False),
)
ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("iv_infusion", re.compile(r"\b(?:intravenous|i\.?v\.?)\s+infusion|\binfused\b", re.IGNORECASE)),
    ("iv_bolus", re.compile(r"\b(?:intravenous|i\.?v\.?)\s+bolus|\bbolus injection", re.IGNORECASE)),
    ("oral", re.compile(r"\boral(?:ly)?\b|\bby mouth\b|\btablets?\b|\bcapsules?\b", re.IGNORECASE)),
)
APPLICATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("APP-14 virtual bioequivalence", re.compile(r"bioequivalen|\bVBE\b|\bBE (?:study|studies|trial)", re.IGNORECASE)),
    ("APP-12 food effect", re.compile(r"food[- ]effect|\bfed\b|high[- ]fat|with food", re.IGNORECASE)),
    ("APP-03 enzyme DDI", re.compile(r"drug[- ]drug interaction|\bDDI\b|\bCYP\d[A-Z]\d+ (?:inhibitor|inducer)", re.IGNORECASE)),
    ("APP-06 pediatric extrapolation", re.compile(r"p(?:a)?ediatric|\bchildren\b|\binfants?\b|\bneonat", re.IGNORECASE)),
    ("APP-07 hepatic impairment", re.compile(r"hepatic impairment", re.IGNORECASE)),
    ("APP-08 renal impairment", re.compile(r"renal impairment", re.IGNORECASE)),
    ("APP-09 pregnancy and lactation", re.compile(r"pregnan|lactation", re.IGNORECASE)),
    ("APP-13 pH-dependent DDI", re.compile(r"pH[- ]dependent|acid[- ]reducing|proton[- ]pump", re.IGNORECASE)),
    ("APP-11 absorption and formulation", re.compile(r"dissolution|\bformulation\b|absorption|biowaiver|\bIVIVC\b|release profile",
                                                     re.IGNORECASE)),
    ("APP-02 FIH translation", re.compile(r"first[- ]in[- ]human|\bFIH\b", re.IGNORECASE)),
    ("APP-18 dose and regimen", re.compile(r"dose selection|dosing regimen|dose adjustment", re.IGNORECASE)),
)
_OBJECTIVE = re.compile(r"\b(?:objectives?|aims?|purpose|goals?)\b", re.IGNORECASE)
_GOAL_VERB = re.compile(r"\bto (?:predict|evaluate|assess|demonstrate|simulate|investigate|establish|determine|"
                        r"develop|build|characteri[sz]e)\b", re.IGNORECASE)
_USE = re.compile(r"\b(?:support|submission|regulatory|waiver|biowaiver|label(?:ling)?|agency|approval|Health Canada|FDA|EMA|"
                  r"filing|dossier|justify|justification)\b", re.IGNORECASE)
# what the results are for, said plainly (a sentence that only says "support" is weaker)
_USE_STRONG = re.compile(r"\b(?:submission|regulatory|waiver|biowaiver|label(?:ling)?|agency|approval|Health Canada|FDA|EMA|"
                         r"filing|dossier)\b", re.IGNORECASE)
_LOCAL = re.compile(r"\b(?:topical|local(?:ly)? acting|inhaled|ophthalmic|intra-?articular)\b", re.IGNORECASE)
_STRENGTHS = re.compile(r"\bstrengths?\b", re.IGNORECASE)
_MG = re.compile(r"(\d+(?:\.\d+)?)\s*mg\b", re.IGNORECASE)
_FASTED_WORDS = re.compile(r"\bfast(?:ed|ing)\b", re.IGNORECASE)
_FED_WORDS = re.compile(r"\bfed\b|\bhigh[- ]fat\b|\bwith (?:a )?(?:meal|food)\b", re.IGNORECASE)
_LARGE = re.compile(r"\bantibod|\bmonoclonal\b|\b[a-z]+mab\b|therapeutic protein|\bpeptides?\b|\bbiologics?\b", re.IGNORECASE)
_ORAL_SOLID = re.compile(r"\btablets?\b|\bcapsules?\b", re.IGNORECASE)

# the drug's disposition
LABEL = "fda-label-"          # the name `compound_sources` gives the FDA label it stores
LINEAR = "linear"             # a drafted "no" for nonlinearity: linear, dose-proportional pharmacokinetics stated
_BCS = re.compile(r"\bBCS\b(?:[^.]{0,40}?\b[Cc]lass)?\s*(IV|I{1,3}|[1-4])\b")
_ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV"}
_NAMES = re.compile(r"\b(CYP\d{1,2}[A-Z]\d{0,2}|UGT\d[A-Z]\d{1,2}|SULT\d[A-Z]\d|FMO\d|CES[12]|P-gp|P-glycoprotein|ABCB1|BCRP|"
                    r"ABCG2|OATP1B[13]|OATP2B1|OAT[13]|OCT[12]|MATE[12](?:-K)?|MRP2)\b")
_UGT_FAMILY = re.compile(r"\bUGTs?\b(?! ?\d)|\bUGT (?:isoforms|isozymes|enzymes)", re.IGNORECASE)
_SAME_NAME = {"P-glycoprotein": "P-gp"}
_TRANSPORTER = re.compile(r"P-gp|ABC|BCRP|OAT|OCT|MATE|MRP")
_DENIED = re.compile(r"\bnot\b|\bno\b|\bneither\b|\bnor\b|\bunlikely\b|\bnegligible\b", re.IGNORECASE)
KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hepatic_metabolism", re.compile(r"metaboli[sz]ed|metabolism|conjugat|glucuronid|oxidative|\bCYP\d|\bUGT", re.IGNORECASE)),
    ("gut_wall_metabolism", re.compile(r"gut[- ]wall|intestinal (?:metabolism|first[- ]pass)", re.IGNORECASE)),
    ("renal_filtration", re.compile(r"(?:excreted|eliminated|recovered) unchanged (?:in|into) (?:the )?urine|unchanged (?:drug )?in "
                                    r"(?:the )?urine|renal excretion|glomerular filtration|renally (?:excreted|cleared|eliminated)",
                                    re.IGNORECASE)),
    ("renal_secretion", re.compile(r"tubular secretion|actively secreted", re.IGNORECASE)),
    ("biliary_excretion", re.compile(r"biliary excretion|excreted (?:in|into) (?:the )?bile", re.IGNORECASE)),
)
_NONLINEAR = re.compile(r"non-?linear|saturab|saturation of|auto-?induc|(?:less|more|greater) than (?:dose[- ])?proportional",
                        re.IGNORECASE)
_LINEAR = re.compile(r"dose[- ]proportional|\blinear (?:and dose-proportional )?pharmacokinetic|pharmacokinetics (?:are|is|were) "
                     r"linear|\blinear (?:and|over|across|within)\b", re.IGNORECASE)
_EHC = re.compile(r"enterohepatic(?:ally)? (?:recycl|recirculat|circulat)", re.IGNORECASE)


@dataclass(frozen=True)
class Sentence:
    text: str
    sha: str
    page: int
    source: str

    def cite(self) -> Citation:
        return Citation(doc_sha256=self.sha, page=self.page, quote=self.text, source=self.source)


def _sentences_of(library: DocumentLibrary, records: list[Any], source: str | None = None) -> list[Sentence]:
    out = []
    for record in records:
        for number, text in enumerate(library.pages(record.sha256), start=1):
            for match in _SENTENCE.finditer(text):
                sentence = " ".join(match.group(0).split()).strip(" -•*#")
                if len(sentence) >= 20:
                    out.append(Sentence(sentence, record.sha256, number, source or record.name))
    return out


def sentences(library: DocumentLibrary) -> list[Sentence]:
    """The proposal's sentences, page by page (the documents the person gave as the proposal; else every document but
    the records code retrieved)."""
    records = [r for r in map(document_record, library.documents()) if r.role != "retrieved_record"]
    return _sentences_of(library, [r for r in records if r.role == "proposal"] or records)


def document_sentences(library: DocumentLibrary) -> list[Sentence]:
    """Every sentence of the project's documents but the records code retrieved: the proposal and the client's files."""
    return _sentences_of(library, [r for r in map(document_record, library.documents()) if r.role != "retrieved_record"])


def label_sentences(library: DocumentLibrary) -> list[Sentence]:
    """The sentences of the FDA label code stored at the project's start (its pharmacokinetics section), if any."""
    return _sentences_of(library, [r for r in map(document_record, library.documents())
                                   if r.role == "retrieved_record" and r.name.startswith(LABEL)], "FDA label")


def _strengths(found: list[Sentence]) -> tuple[list[float], Sentence | None]:
    """The strengths the proposal names ("two strengths: 50 mg and 100 mg"), in order, and the sentence naming them."""
    hit = _first(found, _STRENGTHS, avoid=_MEDIUM, strong=_MG)
    if hit is None:
        return [], None
    doses = list(dict.fromkeys(float(m.group(1)) for m in _MG.finditer(hit.text)))
    return doses, hit if doses else None


def _by_a_person(by: str | None) -> bool:
    return bool(by) and not str(by).startswith(("agent:", "code:", "system"))


def _open(brief: ProjectBrief, path: str) -> bool:
    """Empty, and not a person's answer: "not stated" (MISSING) or "no" (NOT_APPLICABLE) a person chose is kept."""
    record = brief.get(path)
    if record.status in (FieldStatus.MISSING, FieldStatus.NOT_APPLICABLE) and _by_a_person(record.by):
        return False
    return (not locked(brief, path) and record.status not in (FieldStatus.EXTRACTED, FieldStatus.NOT_APPLICABLE)
            and record.value in (None, "", []))


def _first(found: list[Sentence], pattern: re.Pattern[str], *, avoid: re.Pattern[str] | None = None,
           not_in: set[str] = frozenset(), strong: re.Pattern[str] | None = None) -> Sentence | None:
    """The sentence to quote: one that matches; a full sentence before a heading, one with `strong` words before one
    without, the earliest otherwise."""
    hits = [s for s in found if pattern.search(s.text) and not (avoid and avoid.search(s.text)) and s.text not in not_in]
    if not hits:
        return None
    return min(enumerate(hits), key=lambda ih: (not (strong and strong.search(ih[1].text)),
                                                not ih[1].text.endswith((".", "!", "?")), ih[0]))[1]


def read_for_start(library: DocumentLibrary, brief: ProjectBrief, *, by: str = CODE) -> tuple[ProjectBrief, list[str]]:
    """Draft every Start field still empty from the proposal's words (and the two defaults); the paths drafted."""
    found = sentences(library)
    drafted: list[str] = []

    def put(path: str, value: Any, why: str, cites: tuple[Citation, ...] = ()) -> None:
        nonlocal brief
        if not _open(brief, path):
            return
        brief = agent_set(brief, path, value=value, unit=None, citations=cites, status=FieldStatus.DRAFTED,
                          confidence=None, by=by, note=NOTE.format(why=why))
        drafted.append(path)

    if found:
        goal = _first(found, _OBJECTIVE) or _first(found, _GOAL_VERB)
        if goal:
            put("qoi.text", goal.text, "the proposal's objective", (goal.cite(),))
        use = _first(found, _USE, not_in={goal.text} if goal else set(), strong=_USE_STRONG)
        if use:
            put("qoi.context_of_use", use.text, "what the proposal says the results are for", (use.cite(),))
        apps = [(option, hit) for option, pattern in APPLICATIONS if (hit := _first(found, pattern))]
        if apps:
            put("qoi.applications", [o for o, _h in apps], "; ".join(f"{o.split(' ', 1)[1]}: “{h.text[:60]}…”" for o, h in apps),
                tuple(dict.fromkeys(h.cite() for _o, h in apps)))
        forms: dict[str, Sentence] = {}
        for option, pattern, not_medium in FORMS:
            hit = _first(found, pattern, avoid=_MEDIUM if not_medium else None)
            if hit:
                mr = option in ("ir_tablet", "ir_capsule") and _MR.search(hit.text)
                forms.setdefault("mr" if mr else option, hit)
        if forms:
            put("scope.formulation_types", list(forms), "the dosage forms the proposal names", tuple(s.cite() for s in forms.values()))
        # no scenario yet: one per strength the proposal names when it names one route (the owner, 2026-11-08), else one
        # per route (at most two); scenarios already there: a missing route is filled only when the proposal names one
        # route, and each strength no scenario has gets one
        routes = [(option, hit) for option, pattern in ROUTES if (hit := _first(found, pattern, avoid=_MEDIUM))]
        strengths, named_in = _strengths(found)
        items = brief.groups.get("scenarios", ())
        if not items:
            chosen = [routes[0]] * len(strengths) if len(routes) == 1 and strengths else routes[:2]
        else:
            chosen = routes * len(items) if len(routes) == 1 else []
        for i, (option, hit) in enumerate(chosen):
            put(f"scenarios[{i}].route", option, f"the proposal gives the product {option.replace('_', ' ')}", (hit.cite(),))
        if strengths and named_in is not None and (len(routes) == 1 or items):
            doses = [brief.get(f"scenarios[{i}].dose").value for i in range(len(brief.groups.get("scenarios", ())))]
            left = [d for d in strengths if d not in {float(v) for v in doses if isinstance(v, int | float)}]
            for i, dose in enumerate(doses):
                if dose in (None, "") and left:
                    put(f"scenarios[{i}].dose", left.pop(0), "a strength the proposal names", (named_in.cite(),))
            for dose in left:                    # a strength no scenario has: its own scenario, on the first's route
                i = len(brief.groups.get("scenarios", ()))
                route = brief.get("scenarios[0].route").value if i else None
                if route:
                    put(f"scenarios[{i}].route", route, "the route of the proposal's other strengths", (named_in.cite(),))
                    put(f"scenarios[{i}].dose", dose, "a strength the proposal names", (named_in.cite(),))
        # fasted or fed, when the proposal names only one (a dissolution medium is not a meal)
        fasted, fed = _first(found, _FASTED_WORDS, avoid=_MEDIUM), _first(found, _FED_WORDS, avoid=_MEDIUM)
        if (fasted is None) != (fed is None):
            state, hit = ("fasted", fasted) if fasted else ("fed", fed)
            for i in range(len(brief.groups.get("scenarios", ()))):
                put(f"scenarios[{i}].food_state", state, f"the proposal names {state} studies only", (hit.cite(),))
    # the modality: a biologic the proposal names, else a small molecule when PubChem gave a structure or the proposal
    # names a tablet or capsule (the agent read it before; with the agent off it was left empty, the owner, 2026-11-07)
    large = _first(found, _LARGE) if found else None
    oral_solid = _first(found, _ORAL_SOLID, avoid=_MEDIUM) if found else None
    if large:
        put("drug.modality", "large_molecule", "the proposal names a biologic", (large.cite(),))
    elif brief.get("drug.smiles").value:
        put("drug.modality", "small_molecule", "PubChem gives the drug a structure (SMILES)")
    elif oral_solid:
        put("drug.modality", "small_molecule", "the proposal's product is a tablet or capsule", (oral_solid.cite(),))
    local = _first(found, _LOCAL) if found else None
    put("scope.pbpk_model", "full", "the default: the builder makes full (whole-body) PBPK models")
    if local is None:
        put("scope.site_of_action", "systemic", "the default: systemic action (plasma and tissue exposure)")
    brief, more = read_disposition(library, brief, by=by, proposal=found)
    return brief, drafted + more


def _names(found: list[Sentence]) -> dict[str, Sentence]:
    """The enzymes and transporters the sentences name as involved, in order, each with the sentence naming it."""
    names: dict[str, Sentence] = {}
    for s in found:
        if _DENIED.search(s.text):
            continue
        for match in _NAMES.finditer(s.text):
            names.setdefault(_SAME_NAME.get(match.group(1), match.group(1)), s)
        if _UGT_FAMILY.search(s.text) and not any(n.startswith("UGT") for n in names):
            names.setdefault("UGT", s)
    return names


def _disposition(found: list[Sentence]) -> dict[str, tuple[Any, tuple[Sentence, ...]]]:
    """What `found` says of the drug's disposition: field path to (draft, the sentences it rests on)."""
    out: dict[str, tuple[Any, tuple[Sentence, ...]]] = {}
    if bcs := next(((m, s) for s in found if (m := _BCS.search(s.text))), None):
        out["drug.bcs_class"] = (_ROMAN.get(bcs[0].group(1), bcs[0].group(1)), (bcs[1],))
    names = _names(found)
    kinds = [(kind, hit) for kind, pattern in KINDS if (hit := _first(found, pattern, avoid=_DENIED))]
    if transporter := next((s for n, s in names.items() if _TRANSPORTER.match(n)), None):
        kinds.append(("transporter_mediated", transporter))
    if names:
        out["scope.pathways_stated"] = (list(names), tuple(dict.fromkeys(names.values())))
    if kinds:
        out["scope.pathways"] = ([k for k, _h in kinds], tuple(dict.fromkeys(h for _k, h in kinds)))
    if nonlinear := _first(found, _NONLINEAR, avoid=_DENIED):
        out["scope.nonlinearity"] = (nonlinear.text, (nonlinear,))
    elif linear := _first(found, _LINEAR):
        out["scope.nonlinearity"] = (LINEAR, (linear,))
    if ehc := _first(found, _EHC):
        out["scope.ehc"] = (not _DENIED.search(ehc.text), (ehc,))
    return out


def read_disposition(library: DocumentLibrary, brief: ProjectBrief, *, by: str = CODE,
                     proposal: list[Sentence] | None = None) -> tuple[ProjectBrief, list[str]]:
    """Draft the drug's disposition still empty: what the proposal states, else what the stored FDA label states; the
    paths drafted."""
    stated = _disposition(sentences(library) if proposal is None else proposal)
    label = _disposition(label_sentences(library))
    drafted: list[str] = []
    for path in ("drug.bcs_class", "scope.pathways", "scope.pathways_stated", "scope.nonlinearity", "scope.ehc"):
        found, where = ((stated[path], "the proposal") if path in stated
                        else (label[path], "the FDA label (the proposal does not state it)") if path in label else (None, ""))
        if found is None or not _open(brief, path):
            continue
        value, rests_on = found
        shown = ("linear, dose-proportional pharmacokinetics" if value == LINEAR
                 else ", ".join(map(str, value)) if isinstance(value, list) else "yes" if value is True
                 else "no" if value is False else value)
        brief = agent_set(brief, path, value=value, unit=None, citations=tuple(s.cite() for s in rests_on),
                          status=FieldStatus.DRAFTED, confidence=None, by=by,
                          note=f"read by code from {where}: {shown}")
        drafted.append(path)
    return brief, drafted
