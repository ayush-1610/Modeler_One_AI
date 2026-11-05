"""The compound's values from the free structured sources, proposed by code at the project's start (plan 2026-11-05
§3.3; build B). No AI: what a source states plainly is proposed, quoted from the stored answer; what it states
ambiguously (a pKa without acid or base, a binding given as a range or a bound) is left in the stored page for the
literature agent and the person, and the outcome says so.

What is proposed, each through the same checks as the literature agent's values (`evidence.file_check`, the grade):
- PubChem: the molecular weight (a database value); XLogP3 as a predicted logP; each logP and water solubility PubChem
  lists under Experimental Properties with the reference it cites (a database value; "est" marks it predicted).
- The FDA label (openFDA), §12.3: the plasma protein binding, stored as "% bound" (fu = 1 − bound by code).
- ChEMBL: the most acidic and the most basic pKa ChemAxon computes (predicted).

A value already proposed from the same quote is not proposed again, so the start can be run again at no cost.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from modeler_agents.sources import SourceError
from modeler_agents.structured_sources import ChEMBL, OpenFDA, PubChem
from modeler_intake.citations import MIN_QUOTE_CHARS, quote_appears_in
from modeler_project import Workspace
from modeler_project.documents import DocumentLibrary, Retrieval, document_record
from modeler_project.evidence import EvidenceItem, Extraction, Misfiling, SourceRef, SourceType, file_check, new_id
from modeler_project.evidence_register import items, propose
from modeler_project.requirements import RequirementItem

_MW = re.compile(r'"MolecularWeight"\s*:\s*"?(\d+(?:\.\d+)?)"?')
_XLOGP = re.compile(r'"XLogP"\s*:\s*(-?\d+(?:\.\d+)?)')
_LOGP = re.compile(r"^\s*(?:log\s*(?:K\s*ow|P(?:ow)?)\s*=\s*)?(-?\d+(?:\.\d+)?)(?=\s|$|\()", re.IGNORECASE)
_SOLUBILITY = re.compile(
    r"water[^0-9]{0,30}?(\d[\d,]*(?:\.\d+)?)(?:\s*[xX×]\s*10\s*\^?\s*([+\-−]?\d+))?\s*(mg/L|g/L|mg/mL|µg/mL|ug/mL)",
    re.IGNORECASE)
_AT_TEMPERATURE = re.compile(r"at\s*(\d+(?:\.\d+)?)\s*°?\s*C\b")
_ESTIMATED = re.compile(r"\(est\)|\bestimated\b|\bcalculated\b|\bpredicted\b", re.IGNORECASE)
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_BOUND_OR_LIMIT = re.compile(r"[<>≥≤]\s*\d|\b(?:greater|more|less|higher|lower) than\b|\bup to\b|\bat least\b", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")


@dataclass
class SourcesOutcome:
    """What the structured sources gave: for the run record (`AgentRun.finish`) and the Inputs page."""

    proposed: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)     # name, ok, detail, title, url, values
    notes: list[str] = field(default_factory=list)
    status: str = "COMPLETED"
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        return {"proposed": len(self.proposed), "sources": self.sources, "notes": self.notes, "error": self.error}


@dataclass
class _Context:
    ws: Workspace
    library: DocumentLibrary
    requirements: dict[str, RequirementItem]
    actor: str
    outcome: SourcesOutcome
    quoted: set[tuple[str, str]]          # (target, quote) already proposed

    def store(self, text: str, name: str, *, source: str, url: str) -> str:
        version = self.library.add_text(text, name, role="retrieved_record", by=self.actor,
                                        note=f"{source}, read by code at the project's start")
        sha = document_record(version).sha256
        if self.library.has_record:
            self.library.record_retrieval(sha, Retrieval(source=source, held="page", url=url, by=self.actor,
                                                         at=datetime.now(UTC).isoformat()))
        return sha

    def offer(self, *, target: str, value: float, unit: str | None, quote: str, page: str, doc: str, kind: SourceType,
              source: SourceRef, req: str | None = None, conditions: dict[str, str] | None = None, note: str = "",
              stated: bool = True) -> str | None:
        """Propose one value through the literature agent's checks; None when it is not proposed (and why is noted)."""
        if (target, quote) in self.quoted:
            return None
        # code stored the page; a quote not on it is a fault, never proposed (a short JSON pair is matched exactly)
        if not (quote_appears_in(page, quote) if len(quote) >= MIN_QUOTE_CHARS else quote in page):
            self.outcome.notes.append(f"{target}: the quote is not on the stored page ({quote[:60]!r}); not proposed")
            return None
        try:
            unit, filing = file_check(target, value, unit, quote)
        except Misfiling as exc:
            self.outcome.notes.append(f"{target}: {exc}")
            return None
        requirement = self.requirements.get(req or "")
        item = EvidenceItem(id=new_id(), req_id=requirement.req_id if requirement else None, target=target, value=value,
                            unit=unit, source_type=kind, source=source.model_copy(update={"doc_sha256": doc, "page": 1}),
                            quote=quote, extraction=Extraction.TEXT, conditions=conditions or {},
                            purpose=(requirement.purpose if requirement else "") or "model_building",
                            provider="LITERATURE", note="; ".join(x for x in (note, filing) if x))
        stored = propose(self.ws, item, actor=self.actor, requirement=requirement, value_in_quote=stated)
        self.quoted.add((target, quote))
        self.outcome.proposed.append(stored.id)
        return stored.id


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "drug"


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def read_compound_sources(ws: Workspace, library: DocumentLibrary, requirements: list[RequirementItem], *, drug: str,
                          actor: str, pubchem: PubChem | None = None, openfda: OpenFDA | None = None,
                          chembl: ChEMBL | None = None, log_step: Callable[[dict[str, Any]], None] | None = None,
                          ) -> SourcesOutcome:
    """Read PubChem, the FDA label and ChEMBL for `drug`; propose what each states plainly. A source that cannot be
    reached or has nothing for the name is recorded, never fatal."""
    outcome = SourcesOutcome()
    ctx = _Context(ws=ws, library=library, requirements={r.req_id: r for r in requirements}, actor=actor, outcome=outcome,
                   quoted={(e.target, e.quote) for e in items(ws)})
    log = log_step or (lambda _step: None)
    pubchem, openfda, chembl = pubchem or PubChem(), openfda or OpenFDA(), chembl or ChEMBL()
    for name, read in (("PubChem", lambda: _pubchem(ctx, pubchem, drug)), ("FDA label", lambda: _label(ctx, openfda, drug)),
                       ("ChEMBL", lambda: _chembl(ctx, chembl, drug))):
        before = len(outcome.proposed)
        try:
            entry = read()
        except SourceError as exc:
            entry = {"name": name, "ok": False, "detail": str(exc)}
        except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
            # an answer in a shape this module does not read: recorded, never a stop for the other sources
            entry = {"name": name, "ok": False, "detail": f"its answer could not be read ({type(exc).__name__}: {exc})"[:300]}
        entry["values"] = len(outcome.proposed) - before
        outcome.sources.append(entry)
        log({"type": "source", **entry})
    if not any(s["ok"] for s in outcome.sources):
        outcome.status = "NO_SOURCE"
    return outcome


def _pubchem(ctx: _Context, pubchem: PubChem, drug: str) -> dict[str, Any]:
    record = pubchem.properties(drug)
    title = f"PubChem compound {record.cid} ({drug})"
    url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{record.cid}"
    doc = ctx.store(record.text, f"pubchem-properties-{_slug(drug)}.txt", source="PubChem PUG REST", url=record.url)
    source = SourceRef(locator=f"PubChem CID {record.cid}", title=title, url=url)
    if m := _MW.search(record.text):
        ctx.offer(target="phys.mw", value=_number(m.group(1)), unit="g/mol", quote=m.group(0), page=record.text, doc=doc,
                  kind=SourceType.DATABASE, source=source,
                  note="PubChem's molecular weight of the record's form (check free base or salt)")
    if m := _XLOGP.search(record.text):
        ctx.offer(target="phys.logp", value=_number(m.group(1)), unit=None, quote=m.group(0), page=record.text, doc=doc,
                  kind=SourceType.PREDICTED, source=source, req="REQ-phys.logp",
                  conditions={"logP or logD": "logP", "method": "XLogP3, computed by PubChem",
                              "measured or predicted": "predicted"})
    detail = f"CID {record.cid}"
    try:
        experimental = pubchem.experimental(record.cid)
    except SourceError as exc:
        return {"name": "PubChem", "ok": True, "detail": f"{detail}; Experimental Properties not read: {exc}", "title": title,
                "url": url}
    page = experimental.text(drug)
    exp_doc = ctx.store(page, f"pubchem-experimental-{_slug(drug)}.txt", source="PubChem PUG-View", url=experimental.url)
    exp_source = SourceRef(locator=f"PubChem CID {record.cid}, Experimental Properties", title=f"{title}: Experimental "
                           "Properties", url=f"{url}#section=Experimental-Properties")
    pka_unread = 0
    for item in experimental.items:
        line = f"{item.heading}: {item.value} [{item.reference}]" if item.reference else f"{item.heading}: {item.value}"
        estimated = bool(_ESTIMATED.search(item.value))
        said = {"as PubChem cites it": item.reference} if item.reference else {}
        if item.heading == "LogP" and (m := _LOGP.match(item.value)):
            ctx.offer(target="phys.logp", value=_number(m.group(1)), unit=None, quote=line, page=page, doc=exp_doc,
                      kind=SourceType.DATABASE, source=exp_source, req="REQ-phys.logp",
                      conditions={"logP or logD": "logP", **said,
                                  "measured or predicted": "predicted (estimated, as the source says)" if estimated
                                  else "listed as experimental by PubChem"})
        elif item.heading == "Solubility" and (m := _SOLUBILITY.search(item.value)):
            value = _number(m.group(1)) * (10 ** int(m.group(2).replace("−", "-")) if m.group(2) else 1)
            conditions = {"medium": "water", **said}
            if t := _AT_TEMPERATURE.search(item.value):
                conditions["temperature"] = f"{t.group(1)} °C"
            if estimated:
                conditions["measured or predicted"] = "predicted (estimated, as the source says)"
            ctx.offer(target="phys.solubility.ref", value=value, unit=m.group(3), quote=line, page=page, doc=exp_doc,
                      kind=SourceType.DATABASE, source=exp_source, req="REQ-phys.solubility.ref", conditions=conditions,
                      stated=not m.group(2), note=f"{m.group(1)}×10^{m.group(2)} read as {value:g} by code" if m.group(2) else "")
        elif item.heading == "Dissociation Constants":
            pka_unread += 1
    if pka_unread:
        ctx.outcome.notes.append(f"PubChem lists {pka_unread} pKa value(s) without saying acid or base: left on the stored "
                                 "page for the literature agent and you")
    return {"name": "PubChem", "ok": True, "detail": f"{detail}; {len(experimental.items)} experimental item(s)",
            "title": title, "url": url}


def _binding_sentence(text: str) -> tuple[str, float, str] | None:
    """The label's sentence that states the plasma protein binding as one number: (sentence, value, unit)."""
    for paragraph in text.split("\n"):
        for sentence in _SENTENCE.split(paragraph):
            s = sentence.strip()
            lower = s.lower()
            if not (("bound" in lower or "binding" in lower) and "protein" in lower) or "metabolite" in lower:
                continue
            numbers = _PERCENT.findall(s)
            if len(numbers) != 1 or _BOUND_OR_LIMIT.search(s):
                continue
            unbound = re.search(r"unbound|\bfree\b", lower) is not None
            return s, float(numbers[0]), "%" if unbound else "% bound"
    return None


def _label(ctx: _Context, openfda: OpenFDA, drug: str) -> dict[str, Any]:
    label = openfda.label(drug)
    page = label.page()
    e = label.effective
    effective = f"{e[:4]}-{e[4:6]}-{e[6:8]}" if len(e) == 8 and e.isdigit() else e
    title = f"FDA label, {label.brand} ({label.application}), effective {effective}"
    doc = ctx.store(page, f"fda-label-{_slug(label.brand or drug)}-{label.effective}.txt", source="openFDA (FDA drug label)",
                    url=label.url)
    source = SourceRef(locator=f"§{label.section}", title=title, url=label.url)
    if found := _binding_sentence(label.text):
        sentence, value, unit = found
        ctx.offer(target="bind.fu", value=value, unit=unit, quote=sentence, page=page, doc=doc,
                  kind=SourceType.REGULATORY_REVIEW, source=source, req="REQ-bind.fu", conditions={"species": "human"},
                  note=f"the FDA label of {label.brand}, §{label.section}")
    else:
        ctx.outcome.notes.append("the FDA label states no protein binding as one number: left for the literature agent")
    return {"name": "FDA label", "ok": True, "detail": f"§{label.section}", "title": title, "url": label.url}


def _chembl(ctx: _Context, chembl: ChEMBL, drug: str) -> dict[str, Any]:
    molecule = chembl.molecule(drug)
    page = molecule.page()
    title = f"ChEMBL {molecule.chembl_id} ({molecule.name})"
    doc = ctx.store(page, f"chembl-{_slug(drug)}.txt", source="ChEMBL", url=molecule.url)
    source = SourceRef(locator=f"ChEMBL {molecule.chembl_id}, molecule properties", title=title, url=molecule.url)
    for key, kind, most, target in (("cx_most_apka", "acid", "acidic", "phys.pka.acid.1"),
                                    ("cx_most_bpka", "base", "basic", "phys.pka.base.1")):
        raw = molecule.properties.get(key)
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        ctx.offer(target=target, value=value, unit=None, quote=f"{key}: {raw}", page=page, doc=doc,
                  kind=SourceType.PREDICTED, source=source, req="REQ-phys.pka",
                  conditions={"acid or base": kind, "method": f"ChemAxon, computed by ChEMBL (the most {most} pKa)",
                              "measured or predicted": "predicted"})
    return {"name": "ChEMBL", "ok": True, "detail": "computed properties", "title": title, "url": molecule.url}
