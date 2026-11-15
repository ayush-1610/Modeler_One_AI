"use client";

// "Link elsewhere…" on a file's row in Client files (review INT-5; plan 2026-11-14 §2.2.4: a link is changed by linking
// again). The links in force on the file's values (`DeliveryFile.links`: what each covers there, where it sent them, who,
// when and why) are said on the row by the place they sent the values to (`linkPlaces`): a file's facts and its table are
// often two links to one place ("State it…" relinks the concentrations alone, a re-read carries the table's link over
// apart from the facts'), and they move together, so the dose, fed state and LLOQ never stay behind (final review INT-5).
// Here a place's values are linked again with the link form of To do (`LinkEditor`: study and arm, product and batch,
// analyte, each an existing one or a new one), the same collision guard (what the new study holds in that arm is read
// from its card first) and a reason: one `values:assign` with the union of those links' targets, which replaces them
// whole. Values the file sent to another place stay there, and the form says so. Not offered for a blinded file: its
// values are withheld until the plan is signed. The answer is the page, written into the cache (writes.ts).

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { announce } from "@/components/kit/LiveRegion";
import { send, type Schema } from "@/lib/api";
import { fetchResource, useResource } from "@/lib/hooks";
import {
  NEW, analyteChoice, analyteChoices, assignBody, collisions, destinationKey, heldBy, linkPlaces, linkedPiece, targetProblem,
  type Held, type LinkPlace, type LinkTarget,
} from "@/lib/inputsWork";
import { whenText } from "@/lib/words";

import { plural, useDecide, type FileRow } from "./shared";
import { LinkEditor } from "./Unassigned";
import { writePage } from "./writes";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const ASSIGN = "/api/v1/projects/{project_id}/delivery/values:assign" as const;
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
/** How long a card the page has just read stands for what a study holds when a link is sent (else it is read again). */
const FRESH = 10_000;
type Link = Schema<"DeliveryFileLink">;
type Value = Schema<"DeliveryValue">;
type Place = LinkPlace<Link>;

/** The analyte ids a card's values carry. */
const analytesOf = (card: { tables: { values: Value[] }[] } | null | undefined) =>
  [...new Set((card?.tables ?? []).flatMap((t) => t.values.map((v) => v.entity.analyte)).filter((x): x is string => Boolean(x)))];

/** Who linked a place's values and when: each link's person (or the reader, carrying a person's link over a re-read). */
const whoText = (links: Link[]) => links.map((l) => `${l.by === "code" ? "the reader, carried over from a person's link" : l.by} on ${whenText(l.at)}`)
  .filter((x, i, all) => all.indexOf(x) === i).join("; ");

/** The file's links, one line per place its values went to: how many, who and when, and "Link elsewhere…" for them all. */
export function FileLinks({ projectId, file }: { projectId: string; file: FileRow }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!file.links.length) return null;
  const places = linkPlaces(file.links);
  return (
    <ul className="delivery-plain file-links" data-testid={`delivery-file-links-${file.file_id}`}>
      {places.length > 1 && (
        <li className="muted fs-12" data-testid={`delivery-file-places-${file.file_id}`}>Its values went to {places.length} places: each place&apos;s
          values are linked elsewhere on their own, and the others stay where they are.</li>
      )}
      {places.map((p) => {
        const id = p.links[0].assignment;
        return (
          <li key={p.key} data-testid={`delivery-file-link-${file.file_id}-${id}`}>
            <span>{plural(p.values, "value")} linked to {p.words}</span>{" "}
            <span className="muted fs-12" title={p.links.map((l) => `“${l.why}”`).join(" · ")}>by {whoText(p.links)}</span>{" "}
            {file.blinded ? <span className="muted fs-12">Its study is blinded: the link can be changed once the plan is signed.</span>
              : open !== p.key && (
                <button type="button" className="link-btn" onClick={() => setOpen(p.key)} data-testid={`delivery-file-relink-${file.file_id}-${id}`}
                        aria-label={`Link the ${plural(p.values, "value")} of ${file.name} elsewhere`}>Link elsewhere…</button>
              )}
            {open === p.key && <LinkElsewhere projectId={projectId} file={file} place={p} others={places.filter((x) => x !== p)}
                                              onDone={() => setOpen(null)} />}
          </li>
        );
      })}
    </ul>
  );
}

function LinkElsewhere({ projectId, file, place, others, onDone }: {
  projectId: string; file: FileRow; place: Place; others: Place[]; onDone: () => void;
}) {
  const client = useQueryClient();
  const page = useResource(DELIVERY, { project_id: projectId }).data;
  const first = place.links[0];
  const type = first.study ? "study" : "product";
  const subject = first.study ?? first.product ?? "";
  // the values the links cover, as the card of where they are now shows them (their subjects, periods and analyte): read
  // while the form is open, and before the link is sent if it has not come yet
  const now = useResource(CARD, { project_id: projectId, type, subject });
  const was = place.target;
  const [target, setTarget] = useState<LinkTarget>(was);
  const { decide, busy } = useDecide();
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!page?.enabled) return null;
  const analytes = page.analytes;
  const named = (id: string) => analytes.find((a) => a.id === id)?.label ?? id;
  const stated = [...new Set(place.links.map((l) => l.analyte).filter((a): a is string => Boolean(a)))];
  /** The place's values as one piece: the arm and batch they have now are the study's (or product's) own choices, named
   *  there; their analyte is named as the delivery names it (an id is never shown). */
  const pieceOf = (card: { tables: { values: Value[] }[] } | null | undefined) => {
    const values = (card?.tables ?? []).flatMap((t) => t.values)
      .filter((v) => v.file_sha256 === file.sha256 && place.targets.some((t) => v.id === t || v.id.startsWith(`${t}#`)));
    const base = linkedPiece(file.sha256, file.name, values);
    const analyte = base.own.analyte ? { id: base.own.analyte.id, label: named(base.own.analyte.id) } : null;
    return { ...base, own: { arm: null, batch: null, analyte }, fileId: `elsewhere-${file.file_id}`, file: file.name, parts: [] };
  };
  const piece = pieceOf(now.data);
  const same = destinationKey(target) === destinationKey(was);
  const missing = targetProblem(target, analytes) ?? (same ? "It is linked there now: choose another place" : null);

  async function relink(why: string): Promise<boolean> {
    setProblem(null);
    let held: Held = {};
    let uses: string[] = [];
    let mine = piece;
    setChecking(true);
    try {
      // where its values are now (their subjects and periods), and what the new study holds in that arm, read now (never
      // taken as empty): the guard of To do's link table
      mine = pieceOf(now.data ?? await fetchResource(client, CARD, { project_id: projectId, type, subject }, FRESH));
      if (target.study && target.study !== NEW && mine.pairs.length) {
        const card = await fetchResource(client, CARD, { project_id: projectId, type: "study", subject: target.study }, FRESH);
        held = { [target.study]: heldBy(card) };
        uses = analytesOf(card);
      }
    } catch (e) {
      setProblem(`Where its values are now, or what that study holds, could not be read, so its arms are not checked: nothing was linked. (${e instanceof Error ? e.message : String(e)})`);
      return false;
    } finally {
      setChecking(false);
    }
    const clash = collisions([{ row: mine, target }], page!.subjects, held, analytes)[0];
    if (clash) {
      const text = `${file.name} holds ${clash.example}, which study ${clash.study} has in that arm already: in study ${clash.study} each file needs its own arm. Nothing was linked.`;
      setProblem(text);   // said by its alert, not again in the live region (final review A11Y-6)
      return false;
    }
    const sent = { ...target, analyte: analyteChoice(target.analyte, analyteChoices(analytes, mine.own.analyte, uses), analytes, mine.own.analyte) };
    // one call for every value the file has in that place, its facts and its tables together
    const { data, problem: refused } = await decide(() => send("post", ASSIGN, { project_id: projectId }, assignBody(sent, place.targets, why)),
                                                    { refresh: false });
    if (data) {
      writePage(client, projectId, data);
      announce(`The ${plural(place.values, "value")} of ${file.name} are linked again: the earlier ${place.links.length > 1 ? "links" : "link"} to ${place.words} ${place.links.length > 1 ? "are" : "is"} replaced.`);
      onDone();
      return true;
    }
    setProblem(refused ?? "It was not linked.");
    return false;
  }

  return (
    <div className="link-elsewhere" data-testid={`delivery-file-relink-form-${file.file_id}`}>
      <p className="muted fs-13 m-0">Linked now to {place.words}{place.links.length > 1 ? ` by ${place.links.length} links (its facts and its tables)` : ""}.
        Linking again moves all {plural(place.values, "value")} together and replaces {place.links.length > 1 ? "those links" : "that link"} whole:
        their arm, batch and analyte are the ones chosen here.
        {stated.length > 1 ? ` They state ${stated.length} analytes (${stated.map(named).join(", ")}): choose the one for all of them.` : ""}</p>
      {others.length > 0 && (
        <p className="muted fs-13 m-0" data-testid={`delivery-file-relink-others-${file.file_id}`}>The file&apos;s other values stay where they are:{" "}
          {others.map((o) => `${plural(o.values, "value")} linked to ${o.words}`).join("; ")}. Link them elsewhere from their own line.</p>
      )}
      <LinkEditor projectId={projectId} row={piece} target={target} onTarget={setTarget} subjects={page.subjects} analytes={analytes}
                  busy={busy || checking} missing={missing} suggestions={[]} onLink={relink} problem={problem} action="Link elsewhere"
                  used={(study) => (study === first.study ? analytesOf(now.data) : [])} />
      <button type="button" className="link-btn" onClick={onDone} data-testid={`delivery-file-relink-cancel-${file.file_id}`}>Cancel</button>
    </div>
  );
}
