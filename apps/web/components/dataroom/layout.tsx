"use client";

// The Data room in its groups (plan 2026-11-26 §9, slice 5a): Question and Context of Use, Model Input Data, Supporting
// Evidence, Source Records and Data Requests, each with its sections. The API places every part (`room.layout`); each
// section draws today's cards for what it holds, filtered to the values, profiles and decisions placed in it.

import type { ReactNode } from "react";

import { SECTION_STATE, num, type BeResult, type LayoutGroup, type LayoutSection, type Room, type Run, type Value } from "@/lib/dataroom";

import { Card, Dot, Nothing, Row, Sources, Table } from "./kit";
import { Files, QuestionCard } from "./overview";
import { Requirements } from "./requirements";
import { Clinical, Dissolution, Formulation, Observed, Solubility, ValueTable } from "./science";
import { Decisions, Inputs, Plan, Requests } from "./work";

export const OVERVIEW_ID = "overview";

/** The section an address names: a section's own id, else the section an old address (?section=clinical) now opens. */
export function sectionFor(layout: readonly LayoutGroup[], asked: string): string {
  const all = layout.flatMap((g) => g.sections);
  if (all.some((s) => s.id === asked)) return asked;
  return all.find((s) => (s.answers ?? []).includes(asked))?.id ?? OVERVIEW_ID;
}

export function GroupedRail({ layout, current, go }: { layout: readonly LayoutGroup[]; current: string; go: (id: string) => void }) {
  return (
    <>
      <nav className="dr-rail" aria-label="Data room sections" data-testid="dataroom-rail">
        <ul>
          <li>
            <button type="button" className={current === OVERVIEW_ID ? "on" : ""} aria-current={current === OVERVIEW_ID ? "page" : undefined}
                    onClick={() => go(OVERVIEW_ID)} data-testid="rail-overview">
              <span className="dr-dot-wrap"><span className="dr-dot home" aria-hidden /></span><span>Overview</span>
            </button>
          </li>
        </ul>
        {layout.map((g) => (
          <div key={g.id} className="dr-rail-group" data-testid={`rail-group-${g.id}`}>
            <p className="dr-rail-group-title">{g.title}</p>
            <ul>
              {g.sections.map((s) => (
                <li key={s.id}>
                  <button type="button" className={`${current === s.id ? "on" : ""}${s.status === "empty" ? " quiet" : ""}`}
                          aria-current={current === s.id ? "page" : undefined} onClick={() => go(s.id)}
                          data-testid={`rail-${s.id}`} title={`${s.title}: ${SECTION_STATE[s.status]}`}>
                    <Dot status={s.status} /><span>{s.title}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>
      <label className="dr-rail-select">
        <span className="sr-only">Section</span>
        <select value={current} onChange={(e) => go(e.target.value)} data-testid="dataroom-section-select">
          <option value={OVERVIEW_ID}>Overview</option>
          {layout.map((g) => (
            <optgroup key={g.id} label={g.title}>
              {g.sections.map((s) => <option key={s.id} value={s.id}>{s.title} · {SECTION_STATE[s.status]}</option>)}
            </optgroup>
          ))}
        </select>
      </label>
    </>
  );
}

function pick(values: readonly Value[], keys: readonly string[]): Value[] {
  return values.filter((v) => keys.includes(v.key));
}

function BeTable({ room }: { room: Room }) {
  const rows = room.studies.flatMap((s) => (s.be ?? []).map((b) => ({ study: s.study_id, b })));
  if (!rows.length) return null;
  const csr = (b: BeResult) => (b.csr_status === "none" ? "no CSR value" : b.csr_status === "reproduced"
    ? `CSR reproduced (${num(b.csr.ratio)} %)` : `CSR ${num(b.csr.ratio)} %: differs by ${num(b.csr_difference_pp.ratio, 3)} pp`);
  return (
    <Card title="Bioequivalence, computed by code" testId="be-results"
          aside={<span className="muted dr-small">{rows[0].b.rule.split(";").slice(-1)[0]}</span>}>
      <Table label="Bioequivalence" head={["Study", "Metric", "From", "n", "GMR (90 % CI)", "CVw", "BE zone", "Conclusion", "Against the CSR"]}>
        {rows.map(({ study, b }) => (
          <Row key={`${study}-${b.metric}-${b.source}`} testId={`be-${b.metric}-${b.source}`} cells={[
            study, b.label, b.source === "ours" ? "our NCA" : "the client's NCA", String(b.n),
            `${num(b.gmr_percent)} % (${num(b.ci_low_percent)}–${num(b.ci_high_percent)})`,
            b.cv_percent == null ? "–" : `${num(b.cv_percent, 3)} %`,
            b.zone_low_percent == null ? "none" : `${num(b.zone_low_percent)}–${num(b.zone_high_percent)} %`,
            b.within_limits ? "within the limits" : "outside the limits", csr(b)]} />
        ))}
      </Table>
      <p className="muted dr-small">The CVw is computed by code: confirm it against the CRO&apos;s statement (D3).</p>
    </Card>
  );
}

function DoseCardView({ room }: { room: Room }) {
  const d = room.dose_card;
  if (!d) return null;
  const mg = (x: number | null | undefined) => (x == null ? "not known" : `${num(x)} mg`);
  return (
    <Card title="Dose in both bases" testId="dose-card" aside={<Sources chips={d.sources} max={3} />}>
      <ul className="dr-list">
        <li>As written: <strong>{d.dose_written}</strong> ({d.basis === "unknown" ? "basis not stated" : `as the ${d.basis === "salt" ? "salt" : "free base"}`}{d.salt ? `, salt: ${d.salt}` : ""})</li>
        <li>Molecular weight: base {d.mw_base == null ? "not known" : `${num(d.mw_base)} g/mol`}, salt {d.mw_salt == null ? "not known" : `${num(d.mw_salt)} g/mol`}</li>
        <li data-testid="dose-as-base">As the free base (what PK-Sim is given): <strong>{mg(d.dose_as_base_mg)}</strong>; as the salt: {mg(d.dose_as_salt_mg)}</li>
        {d.molar_dose_umol != null && <li>Molar dose: {num(d.molar_dose_umol)} µmol</li>}
      </ul>
      {d.rule && <p className="muted dr-small">{d.rule}</p>}
    </Card>
  );
}

function OtherAnalytes({ room }: { room: Room }) {
  if (!room.other_analytes.length) return <Nothing>The studies measured one analyte each.</Nothing>;
  return (
    <Card title="Metabolites and other analytes" testId="other-analytes">
      <Table label="Other analytes" head={["Study", "Analyte", "Subjects dosed", "Profiles with NCA", "Unit"]}>
        {room.other_analytes.map((s) => (
          <Row key={`${s.study_id}-${s.analyte}`} testId={`other-analyte-${s.analyte}`} cells={[
            s.study_id, s.analyte, String(s.sets.find((x) => x.name === "dosed")?.subjects.length ?? 0), String(s.nca.length),
            s.concentration_unit || "–"]} />
        ))}
      </Table>
      <p className="muted dr-small">Kept as Supporting Evidence: the model is compared with the analyte chosen under Observed PK.</p>
    </Card>
  );
}

function Exclusions({ room }: { room: Room }) {
  const rows = room.studies.flatMap((s) => Object.entries(s.excluded ?? {}).map(([subject, why]) => ({ study: s.study_id, subject, why })));
  if (!rows.length) return null;
  return (
    <Card title="Who is out, and why" testId="conduct-exclusions">
      <Table label="Exclusions" head={["Study", "Subject", "Why"]}>
        {rows.map((r) => <Row key={`${r.study}-${r.subject}`} cells={[r.study, r.subject, r.why]} />)}
      </Table>
    </Card>
  );
}

/** One section of the page in its groups: what the API placed in it, drawn with today's cards. */
export function LayoutBody({ section, room, run, projectId, go }: {
  section: LayoutSection; room: Room; run: Run | null; projectId: string; go: (id: string) => void;
}): ReactNode {
  const all = [...room.substance, ...room.adme, ...room.products];
  const studyValues = room.studies.flatMap((s) => s.facts);
  const parts = section.parts.map((part) => {
    switch (part) {
      case "question": return <QuestionCard key={part} room={room} />;
      case "requirements": return <Requirements key={part} room={room} go={go} />;
      case "products": return pick(room.products, section.values).length
        ? <Card key={part} title="Values" testId={`values-${section.id}`}><ValueTable values={pick(room.products, section.values)} label={section.title} /></Card> : null;
      case "composition": return <Formulation key={part} room={room} />;
      case "substance": return pick(room.substance, section.values).length
        ? <Card key={part} title="Values" testId={`values-${section.id}`}><ValueTable values={pick(room.substance, section.values)} label={section.title} /></Card> : null;
      case "solubility": return <Solubility key={part} room={room} />;
      case "dose_card": return <DoseCardView key={part} room={room} />;
      case "dissolution": return <Dissolution key={part} room={room} only={section.dissolution} checks={section.id !== "release"} />;
      case "studies": return <Clinical key={part} room={room} />;
      case "observed": return <Observed key={part} room={room} />;
      case "be": return <BeTable key={part} room={room} />;
      case "plan": return <Plan key={part} room={room} />;
      case "inputs": return <Inputs key={part} room={room} projectId={projectId} />;
      case "conduct_values": return pick(studyValues, section.values).length
        ? <Card key={part} title="Facts" testId={`values-${section.id}`}><ValueTable values={pick(studyValues, section.values)} label={section.title} /></Card> : null;
      case "exclusions": return <Exclusions key={part} room={room} />;
      case "other_analytes": return <OtherAnalytes key={part} room={room} />;
      case "adme": case "other_values": return pick([...all, ...studyValues], section.values).length
        ? <Card key={part} title="Values" testId={`values-${section.id}`}><ValueTable values={pick([...all, ...studyValues], section.values)} label={section.title} /></Card> : null;
      case "files": return <Files key={part} room={room} run={run} />;
      case "requests": return <Requests key={part} room={room} />;
      default: return null;
    }
  });
  const empty = !section.count && !section.decisions.length;
  return (
    <>
      {empty && <Nothing>Nothing in this delivery belongs here yet.</Nothing>}
      {parts}
      {section.decisions.length > 0 && (
        <section className="dr-section-decisions" aria-label="Decisions" data-testid={`decisions-${section.id}`}>
          <h3 className="dr-subtitle">Decisions</h3>
          <Decisions room={room} ids={section.decisions} />
        </section>
      )}
    </>
  );
}
