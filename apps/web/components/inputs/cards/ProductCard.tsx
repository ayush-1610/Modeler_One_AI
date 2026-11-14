"use client";

// A product's one card on Products and dissolution (plan 2026-11-14 slice 3; the design text's ProductCard): its name and
// batches, its confirm path (ConfirmPath: the delivery's or the sheet form's), its dissolution per medium (each profile
// drawn with its PK-Sim Weibull fit, observed in amber and the fit in blue as everywhere in the app, its t50 and shape,
// "Use as release" to make that fit the formulation's release, f2 against the reference on the test product's card),
// what is not loaded with it (the delivery's held-back attributes) and the files it was read from. The dissolution
// profiles of no product's card are listed after the cards, with the same rows.

import { useState } from "react";

import type { Comparison, Profile } from "@/components/client/types";
import { send } from "@/lib/api";
import { cardAnchor, normLabel, type Subject } from "@/lib/inputsWork";
import { valueWord } from "@/lib/words";

import { ReleaseView } from "../DatasetView";
import type { Run } from "../InputsTodo";

import { CardHead, ConfirmPath, cardStatus, type CardEnv } from "./ConfirmPath";
import { CardFiles } from "./StudyCard";

const sig = (x: number | null | undefined) => (x === null || x === undefined ? "—" : String(+x.toPrecision(3)));

/** Whether a dissolution profile is this product's: its product as the profile names it, by the card's name or another
 *  name the sheet form gave it. */
export function productOf(s: Subject) {
  const names = new Set([s.label, ...s.aliases, ...s.groups.map((g) => g.title.replace(/^Product /, ""))].map(normLabel));
  return (p: Profile) => names.has(normLabel(String(p.key.product ?? "")));
}

/** One dissolution profile: drawn (unless its sheet's own reading draws it on the card already), its fit, and "Use as
 *  release" with the formulation's name. */
function ProfileLine({ p, projectId, run, product, drawn }: { p: Profile; projectId: string; run: Run; product: string; drawn: boolean }) {
  const [name, setName] = useState(product);
  const [problem, setProblem] = useState<string | null>(null);
  const fit = p.fit;
  return (
    <li className="profile-line" data-testid={`profile-${p.id}`}>
      {drawn ? <p className="m-0 fs-13"><strong>{p.label}</strong> <span className="muted">· drawn below, as the sheet form read it</span></p>
        : <ReleaseView p={p} />}
      {drawn && fit && fit.t50_min !== null && <p className="m-0 fs-13">t50 {sig(fit.t50_min)} min · shape {sig(fit.shape)}</p>}
      {p.release_model !== "Table" ? (
        <form className="row gap-6 profile-use" onSubmit={async (e) => {
          e.preventDefault();
          if (!name.trim()) return;
          setProblem(await run(() => send("post", "/api/v1/projects/{project_id}/dissolution/{profile_id}:propose",
                                          { project_id: projectId, profile_id: p.id }, { formulation: name.trim() }),
                               `${p.label}: its Weibull fit is proposed as the release of ${name.trim()}; it flows into the formulation.`));
        }}>
          <label className="delivery-pick">Formulation
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="formulation name"
                   aria-label={`the formulation ${p.label} is the release of`} />
          </label>
          <button type="submit" className="btn small" disabled={!name.trim()}>Use as release</button>
        </form>
      ) : <p className="muted m-0 fs-12">Read as a table: no Weibull fit to use as the release.</p>}
      {problem && <p className="inline-issue error" role="alert">{problem}</p>}
    </li>
  );
}

/** The dissolution profiles of a product (or of no product), with f2 against the reference where this product is the
 *  test. */
export function Dissolution({ profiles, comparisons, label, projectId, run, product, drawnIds = new Set(), testId }: {
  profiles: Profile[]; comparisons: Comparison[]; label: (id: string) => string; projectId: string; run: Run; product: string;
  /** profiles its sheet's reading already draws on the card */
  drawnIds?: ReadonlySet<string>;
  testId: string;
}) {
  const mine = new Set(profiles.map((p) => p.id));
  const f2 = comparisons.filter((c) => mine.has(c.test));
  if (!profiles.length) return null;
  return (
    <section className="delivery-block card-section" data-testid={testId}>
      <div className="delivery-block-head"><h3>Dissolution</h3><span className="muted fs-13">{profiles.length} profile{profiles.length === 1 ? "" : "s"}</span></div>
      <p className="muted m-0 fs-13">Pick the profile that best represents release in the body. Its Weibull fit (t50, shape) becomes the
        formulation&apos;s release.</p>
      <ul className="profile-lines">
        {profiles.map((p) => <ProfileLine key={p.id} p={p} projectId={projectId} run={run} product={product} drawn={drawnIds.has(p.label)} />)}
      </ul>
      {f2.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Test vs reference</th><th>Condition</th><th className="num">f2</th><th>Verdict</th></tr></thead>
            <tbody>
              {f2.map((c) => (
                <tr key={`${c.test}-${c.reference}`} data-testid="f2-row">
                  <td>{label(c.test)}<div className="muted fs-12">vs {label(c.reference)}</div></td>
                  <td>{c.condition}</td>
                  <td className="num">{c.f2 ?? "—"}</td>
                  <td>{c.applicable ? <span className={`chip ${c.similar ? "low" : "high"}`}>{c.similar ? "similar" : "not similar"}</span>
                    : <span className="muted fs-13">{c.reasons.join("; ")}</span>}
                    <div className="muted fs-12">{c.ruleset}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function ProductCard({ subject, env, open, onToggle, profiles, comparisons, label }: {
  subject: Subject; env: CardEnv; open: boolean; onToggle: () => void;
  /** the dissolution profiles of this product */
  profiles: Profile[]; comparisons: Comparison[]; label: (id: string) => string;
}) {
  const batches = subject.row?.batches.map((b) => b.label) ?? [];
  // the profiles its sheet-form group draws on the card already (a profile item, on a card confirmed with the sheet form):
  // not drawn twice
  const drawn = new Set(subject.path !== "sheet-form" ? [] : subject.groups.flatMap((g) => g.items.filter((i) => i.release)
    .map((i) => (i.release as unknown as Profile).label)));
  return (
    <article className="subject-card product-card" data-testid={cardAnchor(subject)} id={cardAnchor(subject)} data-path={subject.path}>
      <CardHead subject={subject} status={cardStatus(subject, env.work)} open={open} onToggle={onToggle}>
        {batches.length > 0 && <span className="muted fs-13">batch{batches.length === 1 ? "" : "es"} {batches.join(", ")}</span>}
        {profiles.length > 0 && <span className="muted fs-13">{profiles.length} dissolution profile{profiles.length === 1 ? "" : "s"}</span>}
      </CardHead>
      {open && (
        <div id={`${cardAnchor(subject)}-body`}>
          <ConfirmPath subject={subject} env={env} files={<CardFiles subject={subject} env={env} />}
                       observed={<Dissolution profiles={profiles} comparisons={comparisons} label={label} projectId={env.projectId} run={env.run}
                                              product={subject.label} drawnIds={drawn} testId={`card-dissolution-${subject.key}`} />} />
        </div>
      )}
    </article>
  );
}

/** A product's role as the dissolution names it (TEST, RLD, …), in words. */
export const roleWord = (p: Profile) => valueWord(String(p.key.role ?? ""));
