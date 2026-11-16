"use client";

// A product's one card on Products and dissolution (plan 2026-11-14 slice 3; the design text's ProductCard): its name and
// batches, its confirm path (ConfirmPath: the delivery's or the sheet form's), its dissolution per medium (each profile
// drawn with its PK-Sim Weibull fit, observed in amber and the fit in blue as everywhere in the app, its t50 and shape,
// "Use as release" to make that fit the formulation's release, f2 against the reference on the test product's card),
// what is not loaded with it (the delivery's held-back attributes) and the files it was read from. The dissolution
// profiles of no product's card are listed after the cards, with the same rows.
//
// The card says what of the product is in the model (final review OWN-10): confirming keeps its dissolution profile, and
// its release is set only once a profile's fit is used as the formulation's release. While it is not, the card's first
// action is "Use this profile as the release", and a tablet study that needs it makes that the card's open work. A
// profile is named in full once (its line in Dissolution); elsewhere on the card by what tells it from the others.

import Link from "next/link";
import { useState } from "react";

import type { Comparison, Profile } from "@/components/client/types";
import { send } from "@/lib/api";
import { cardAnchor, normLabel, releaseAnchor, type Subject } from "@/lib/inputsWork";
import { ASK_FORMULATION, inputsHref, valueWord } from "@/lib/words";

import { releaseAfter } from "../after";
import { ReleaseView } from "../DatasetView";
import type { Run } from "../InputsTodo";

import { CardHead, ConfirmPath, cardStatus, type CardEnv } from "./ConfirmPath";
import { CardFiles } from "./StudyCard";

const sig = (x: number | null | undefined) => (x === null || x === undefined ? "—" : String(+x.toPrecision(3)));

/** A profile's name without what the card already says (its product's name and role): "phosphate pH 6.8 · batch B1 ·
 *  USP 2 paddle · 50 rpm" on Test 10 mg's card. The whole name where nothing is left. */
export function profileShort(label: string, said: string[]): string {
  const drop = new Set(said.filter(Boolean).map(normLabel));
  const left = label.split(" · ").filter((part) => !drop.has(normLabel(part)));
  return left.length ? left.join(" · ") : label;
}
/** A profile that can be a formulation's release: one read as a curve, with a Weibull fit. */
const usable = (p: Profile) => p.release_model !== "Table" && Boolean(p.fit && p.fit.t50_min !== null);
/** Propose a profile's fit as the release of the formulation `name` (`dissolution:propose`). */
const proposeRelease = (projectId: string, run: Run, p: Profile, name: string) =>
  run(() => send("post", "/api/v1/projects/{project_id}/dissolution/{profile_id}:propose", { project_id: projectId, profile_id: p.id },
                 { formulation: name }),
      `Its dissolution profile is proposed as the release of the formulation “${name}”; it flows into the model.`, releaseAfter(projectId));

/** Whether a dissolution profile is this product's: its product as the profile names it, by the card's name or another
 *  name the sheet form gave it. */
export function productOf(s: Subject) {
  const names = new Set([s.label, ...s.aliases, ...s.groups.map((g) => g.title.replace(/^Product /, ""))].map(normLabel));
  return (p: Profile) => names.has(normLabel(String(p.key.product ?? "")));
}

/** One dissolution profile: drawn (unless its sheet's own reading draws it on the card already), its fit, and "Use as
 *  release" with the formulation's name. */
function ProfileLine({ p, projectId, run, product, drawn, notes, short }: {
  p: Profile; projectId: string; run: Run; product: string; drawn: boolean;
  /** what the register says of this profile: a later file replaced it, or a file was kept over another */
  notes: string[];
  /** the name the card says it by (the sheet form's reading below names it in full) */
  short: string;
}) {
  const [name, setName] = useState(product);
  const [problem, setProblem] = useState<string | null>(null);
  const fit = p.fit;
  return (
    <li className="profile-line" data-testid={`profile-${p.id}`}>
      {drawn ? <p className="m-0 fs-13"><strong>{short}</strong> <span className="muted">· drawn below, as the sheet form read it</span></p>
        : <ReleaseView p={p} />}
      {p.files.length > 0 && <p className="muted m-0 fs-12" data-testid={`profile-files-${p.id}`}>From {p.files.join(", ")}</p>}
      {notes.length > 0 && <ul className="flags" data-testid={`profile-notes-${p.id}`}>{notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      {drawn && fit && fit.t50_min !== null && <p className="m-0 fs-13">t50 {sig(fit.t50_min)} min · shape {sig(fit.shape)}</p>}
      {p.release_model !== "Table" ? (
        <form className="row gap-6 profile-use" onSubmit={async (e) => {
          e.preventDefault();
          if (!name.trim()) return;
          setProblem(await proposeRelease(projectId, run, p, name.trim()));
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
/** The register's notes on one profile ("<label>: b.xlsx replaces a.xlsx", "<label>: a.xlsx kept over b.xlsx (selected on
 *  Inputs)"), without its label; the notes of a file it could not read name no profile (`dissolutionNotes`). */
export const profileNotes = (p: Profile, problems: string[]) =>
  problems.filter((x) => x.startsWith(`${p.label}: `)).map((x) => x.slice(p.label.length + 2));
/** The register's notes that name no profile: a file's dissolution rows it could not read. */
export const dissolutionNotes = (profiles: Profile[], problems: string[]) =>
  problems.filter((x) => !profiles.some((p) => x.startsWith(`${p.label}: `)));

export function Dissolution({ profiles, comparisons, label, projectId, run, product, drawnIds = new Set(), testId, problems = [] }: {
  profiles: Profile[]; comparisons: Comparison[]; label: (id: string) => string; projectId: string; run: Run;
  /** the product whose card this is ("" for the profiles of no product): its profiles are named without its name */
  product: string;
  /** profiles its sheet's reading already draws on the card */
  drawnIds?: ReadonlySet<string>;
  testId: string;
  /** the register's notes (a profile replaced by a later file, or kept over one; a file's rows not read) */
  problems?: string[];
}) {
  const mine = new Set(profiles.map((p) => p.id));
  const f2 = comparisons.filter((c) => mine.has(c.test));
  if (!profiles.length) return null;
  // on a product's card, a profile is said without the product's name and role (the card's title says them)
  const short = (p: Profile) => (product ? profileShort(p.label, [product, String(p.key.product ?? ""), String(p.key.role ?? "")]) : p.label);
  const byId = new Map(profiles.map((p) => [p.id, p] as const));
  return (
    <section className="delivery-block card-section" data-testid={testId}>
      <div className="delivery-block-head"><h3>Dissolution</h3><span className="muted fs-13">{profiles.length} profile{profiles.length === 1 ? "" : "s"}</span></div>
      <p className="muted m-0 fs-13">Pick the profile that best represents release in the body. Its Weibull fit (t50, shape) becomes the
        formulation&apos;s release.</p>
      <ul className="profile-lines">
        {profiles.map((p) => <ProfileLine key={p.id} p={p} projectId={projectId} run={run} product={product} drawn={drawnIds.has(p.label)}
                                          notes={profileNotes(p, problems)} short={short(p)} />)}
      </ul>
      {f2.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Test vs reference</th><th>Condition</th><th className="num">f2</th><th>Verdict</th></tr></thead>
            <tbody>
              {f2.map((c) => (
                <tr key={`${c.test}-${c.reference}`} data-testid="f2-row">
                  {/* this product's profile by what tells it apart; the reference by its product and role (the condition is beside) */}
                  <td>{byId.has(c.test) && product ? short(byId.get(c.test)!) : label(c.test)}
                    <div className="muted fs-12">vs {label(c.reference).split(" · ").slice(0, 2).join(" · ")}</div></td>
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

/** What of the product the model holds (final review OWN-10): its release as a formulation, or that it is not set, with
 *  "Use this profile as the release" as the card's first action (one profile with a fit), the profiles to choose from
 *  (several), or what to do when no profile can be one (add the dissolution file, ask the client). */
function ReleaseLine({ subject, profiles, release, env }: {
  subject: Subject; profiles: Profile[]; release: { name: string | null; needed: boolean }; env: CardEnv;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const can = profiles.filter(usable);
  const id = releaseAnchor(subject);
  if (release.name) {
    return <p className="card-release m-0 fs-13" data-testid={id} id={id}>In the model as the formulation “{release.name}”: its release
      is set from a dissolution profile&apos;s fit (under Formulations in the model, below the cards).</p>;
  }
  const kept = subject.done && profiles.length > 0;
  // a profile's fit is used as a release only once a person confirmed its product's dissolution data (the API refuses it
  // before: `client_review.product_confirmed`); the card says so first and takes the person to that Confirm (round 4: the
  // step bar's "use a product's dissolution profile as its release" lands here)
  const groupOf = (p: Profile) => subject.groups.find((g) => g.kind === "product" && g.items.some((i) => i.id === p.id));
  const first = can.length === 1 ? groupOf(can[0]) : undefined;
  const waiting = can.length === 1 && first?.state !== "confirmed";
  const toConfirm = () => {
    const at = (first && document.querySelector<HTMLElement>(`[data-testid="${CSS.escape(`confirm-${first.id}`)}"]`))
      || document.querySelector<HTMLElement>(`[data-testid="${CSS.escape(`confirm-sheet-${subject.key}`)}"]`);
    at?.scrollIntoView({ block: "center", behavior: "smooth" });
    at?.focus({ preventScroll: true });
  };
  return (
    <section className="card-section card-release" data-testid={id} id={id}>
      <p className="m-0 fs-13"><strong>{kept ? "Its dissolution profile is kept; the formulation's release is not set yet"
        : "The formulation's release is not set yet"}</strong>{release.needed ? ": a tablet or capsule study needs it." : "."}</p>
      {waiting ? (
        <div className="row gap-6 items-center" data-testid={`${id}-confirm-first`}>
          <button type="button" className="btn" onClick={toConfirm} data-testid={`${id}-to-confirm`}>Confirm its data first</button>
          <span className="muted fs-13">its dissolution profile (t50 {sig(can[0].fit?.t50_min)} min · shape {sig(can[0].fit?.shape)}) becomes the
            release of the formulation “{subject.label}” once you have confirmed the product&apos;s data on this card (&ldquo;Confirm&rdquo;,
            below); then &ldquo;Use this profile as the release&rdquo; is offered here</span>
        </div>
      ) : can.length === 1 ? (
        <div className="row gap-6 items-center">
          <button type="button" className="btn primary" data-testid={`${id}-use`}
                  onClick={async () => setProblem(await proposeRelease(env.projectId, env.run, can[0], subject.label))}>
            Use this profile as the release</button>
          <span className="muted fs-13">its Weibull fit (t50 {sig(can[0].fit?.t50_min)} min · shape {sig(can[0].fit?.shape)}) becomes the release
            of the formulation “{subject.label}”</span>
        </div>
      ) : can.length > 1 ? (
        <p className="muted m-0 fs-13">Choose the profile that best represents release in the body under Dissolution, below, and use it as the
          release.</p>
      ) : (
        // what to do, as controls (round 5: said in words only, the step bar's "add a product's dissolution data" landed on
        // nothing to press): its dissolution file, added with Add data, or the client, asked under To do
        <div className="row gap-6 items-center" data-testid={`${id}-add`}>
          {env.onAddData && (
            <button type="button" className="btn" onClick={() => env.onAddData?.(subject.label)} data-testid={`${id}-add-file`}
                    aria-label={`Add its dissolution file… (product ${subject.label})`}>Add its dissolution file…</button>
          )}
          <span className="muted fs-13">no dissolution profile with a fit is here{env.onAddData ? "" : ": add the product's dissolution file (Add data)"};
            or{" "}
            <Link href={inputsHref(env.projectId, { area: "todo", query: `at=${ASK_FORMULATION}` })} prefetch={false}
                  aria-label={`ask the client for the dissolution data of ${subject.label}`}>ask the client</Link> for it</span>
        </div>
      )}
      {problem && <p className="inline-issue error" role="alert">{problem}</p>}
    </section>
  );
}

export function ProductCard({ subject, env, open, onToggle, profiles, comparisons, label, problems = [], release }: {
  subject: Subject; env: CardEnv; open: boolean; onToggle: () => void;
  /** the dissolution profiles of this product */
  profiles: Profile[]; comparisons: Comparison[]; label: (id: string) => string;
  /** the dissolution register's notes (each profile's are said on its line) */
  problems?: string[];
  /** its release in the model (`releaseOf`): the formulation of its name, and whether a tablet study needs it */
  release: { name: string | null; needed: boolean };
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
        {!release.name && (release.needed || profiles.some(usable)) && (
          <span className={`chip ${release.needed ? "medium" : "neutral"}`} data-testid={`card-release-chip-${subject.key}`}>release not set</span>
        )}
      </CardHead>
      {open && (
        <div id={`${cardAnchor(subject)}-body`}>
          <ReleaseLine subject={subject} profiles={profiles} release={release} env={env} />
          <ConfirmPath subject={subject} env={env} files={<CardFiles subject={subject} env={env} />}
                       observed={<Dissolution profiles={profiles} comparisons={comparisons} label={label} projectId={env.projectId} run={env.run}
                                              product={subject.label} drawnIds={drawn} testId={`card-dissolution-${subject.key}`} problems={problems} />} />
        </div>
      )}
    </article>
  );
}

/** A product's role as the dissolution names it (TEST, RLD, …), in words. */
export const roleWord = (p: Profile) => valueWord(String(p.key.role ?? ""));
