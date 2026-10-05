"""Open literature over public REST APIs (the T-22 fallbacks; used directly while the MCP servers are not deployed).

Europe PMC: search (PubMed, PMC and preprints with abstracts), and the full text of open-access articles as JATS XML,
turned into text with tables kept as rows so a quote of a table row can be checked. Only what the API returns is used:
a paper that is not open access becomes an access request for a person, never an unofficial copy (plan §8.3).

The HTTP transport is injectable (tests use a mock; the build container has no route to these hosts, the server must,
decision D-17).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx

EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Paper:
    id: str
    source: str
    pmid: str | None
    pmcid: str | None
    doi: str | None
    title: str
    authors: str
    journal: str
    year: int | None
    open_access: bool
    abstract: str


class EuropePMC:
    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout_s: float = 30.0):
        self._transport = transport
        self._timeout = timeout_s

    def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise SourceError(f"Europe PMC is not reachable from this host ({type(exc).__name__})") from exc
        if response.status_code == 404:
            raise SourceError("not found in Europe PMC (or not open access)")
        if response.status_code != 200:
            raise SourceError(f"Europe PMC answered HTTP {response.status_code}")
        return response

    def search(self, query: str, *, page_size: int = 10) -> list[Paper]:
        data = self._get(f"{EUROPE_PMC}/search", {"query": query, "format": "json", "resultType": "core",
                                                  "pageSize": max(1, min(page_size, 25))}).json()
        out = []
        for hit in (data.get("resultList") or {}).get("result", []):
            journal = ((hit.get("journalInfo") or {}).get("journal") or {}).get("title", "")
            year = hit.get("pubYear")
            out.append(Paper(
                id=str(hit.get("id", "")), source=str(hit.get("source", "")), pmid=hit.get("pmid"), pmcid=hit.get("pmcid"),
                doi=hit.get("doi"), title=str(hit.get("title", "")).strip(), authors=str(hit.get("authorString", "")),
                journal=str(journal), year=int(year) if str(year or "").isdigit() else None,
                open_access=hit.get("isOpenAccess") == "Y", abstract=str(hit.get("abstractText") or ""),
            ))
        return out

    def full_text(self, pmcid: str) -> str:
        """The open-access full text as plain text (title, abstract, sections, tables as rows)."""
        xml = self._get(f"{EUROPE_PMC}/{pmcid}/fullTextXML").text
        return jats_to_text(xml)


def _text(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def jats_to_text(xml: str) -> str:
    """JATS article XML → readable text; every table row becomes ``cell | cell | …`` under its label and caption."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SourceError(f"the full text is not valid XML: {exc}") from exc
    lines: list[str] = []
    title = _text(root.find(".//article-title"))
    if title:
        lines.append(f"# {title}")
    abstract = root.find(".//abstract")
    if abstract is not None:
        lines += ["## Abstract", _text(abstract)]

    def walk(node: ET.Element, depth: int) -> None:
        for child in node:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "sec":
                heading = _text(child.find("title"))
                if heading:
                    lines.append("#" * min(depth + 2, 6) + " " + heading)
                walk(child, depth + 1)
            elif tag == "p":
                text = _text(child)
                if text:
                    lines.append(text)
                for table in child.iter():
                    if table.tag.rsplit("}", 1)[-1] == "table-wrap":
                        emit_table(table)
            elif tag == "table-wrap":
                emit_table(child)
            elif tag in ("list", "disp-quote", "boxed-text", "fig"):
                text = _text(child)
                if text:
                    lines.append(text)

    def emit_table(table: ET.Element) -> None:
        label, caption = _text(table.find("label")), _text(table.find("caption"))
        lines.append(f"[{label or 'Table'}] {caption}".strip())
        for row in table.iter():
            if row.tag.rsplit("}", 1)[-1] == "tr":
                cells = [_text(c) for c in row if c.tag.rsplit("}", 1)[-1] in ("td", "th")]
                if any(cells):
                    lines.append(" | ".join(cells))
        foot = _text(table.find("table-wrap-foot"))
        if foot:
            lines.append(foot)

    body = root.find(".//body")
    if body is not None:
        walk(body, 0)
    return "\n".join(lines)
