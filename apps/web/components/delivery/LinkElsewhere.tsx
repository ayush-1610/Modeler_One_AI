"use client";

// "Link elsewhere…" on a file's row in Client files (review INT-5; plan 2026-11-14 §2.2.4: a link is changed by linking
// again). A person's link in force on the file's values (`DeliveryFile.links`: what it covers there, where it sent them,
// who, when and why) is said on the row; once linked a file left To do's link table, so a wrong link stayed wrong. Here it
// is linked again with the link form of To do (`LinkEditor`: study and arm, product and batch, analyte, each an existing
// one or a new one), the same collision guard (what the new study holds in that arm is read from its card first) and a
// reason: one `values:assign` with the link's own targets, which replaces it whole. Not offered for a blinded file: its
// values are withheld until the plan is signed. The answer is the page, written into the cache (writes.ts).

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { announce } from "@/components/kit/LiveRegion";
import { send, type Schema } from "@/lib/api";
import { fetchResource, useResource } from "@/lib/hooks";
import {
  NEW, analyteChoice, analyteChoices, assignBody, collisions, destinationKey, heldBy, linkTarget, linkWords, linkedPiece, targetProblem,
  type Held, type LinkTarget,
} from "@/lib/inputsWork";
import { whenText } from "@/lib/words";

import { Problem, plural, useDecide, type FileRow } from "./shared";
import { LinkEditor } from "./Unassigned";
import { writePage } from "./writes";

const DELIVERY = "/api/v1/projects/{project_id}/delivery" as const;
const ASSIGN = "/api/v1/projects/{project_id}/delivery/values:assign" as const;
const CARD = "/api/v1/projects/{project_id}/delivery/subjects/{type}/{subject}" as const;
/** How long a card the page has just read stands for what a study holds when a link is sent (else it is read again). */
const FRESH = 10_000;
type Link = Schema<"DeliveryFileLink">;
type Value = Schema<"DeliveryValue">;

/** The analyte ids a card's values carry. */
const analytesOf = (card: { tables: { values: Value[] }[] } | null | undefined) =>
  [...new Set((card?.tables ?? []).flatMap((t) => t.values.map((v) => v.entity.analyte)).filter((x): x is string => Boolean(x)))];

/** The file's links, one line each: where its values went, how many, who and when, and "Link elsewhere…". */
export function FileLinks({ projectId, file }: { projectId: string; file: FileRow }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!file.links.length) return null;
  return (
    <ul className="delivery-plain file-links" data-testid={`delivery-file-links-${file.file_id}`}>
      {file.links.map((l) => (
        <li key={l.assignment} data-testid={`delivery-file-link-${file.file_id}-${l.assignment}`}>
          <span>{plural(l.values, "value")} linked to {linkWords(l)}</span>{" "}
          <span className="muted fs-12" title={`“${l.why}”`}>by {l.by === "code" ? "the reader, carried over from a person's link" : l.by} on {whenText(l.at)}</span>{" "}
          {file.blinded ? <span className="muted fs-12">Its study is blinded: the link can be changed once the plan is signed.</span>
            : open !== l.assignment && (
              <button type="button" className="link-btn" onClick={() => setOpen(l.assignment)} data-testid={`delivery-file-relink-${file.file_id}-${l.assignment}`}
                      aria-label={`Link the ${plural(l.values, "value")} of ${file.name} elsewhere`}>Link elsewhere…</button>
            )}
          {open === l.assignment && <LinkElsewhere projectId={projectId} file={file} link={l} onDone={() => setOpen(null)} />}
        </li>
      ))}
    </ul>
  );
}

function LinkElsewhere({ projectId, file, link, onDone }: { projectId: string; file: FileRow; link: Link; onDone: () => void }) {
  const client = useQueryClient();
  const page = useResource(DELIVERY, { project_id: projectId }).data;
  const type = link.study ? "study" : "product";
  const subject = link.study ?? link.product ?? "";
  // the values the link covers, as the card of where they are now shows them (their subjects, periods and analyte): read
  // while the form is open, and before the link is sent if it has not come yet
  const now = useResource(CARD, { project_id: projectId, type, subject });
  const was = linkTarget(link);
  const [target, setTarget] = useState<LinkTarget>(was);
  const { decide, busy } = useDecide();
  const [checking, setChecking] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (!page?.enabled) return null;
  const analytes = page.analytes;
  /** The link's values as one piece: the arm and batch they have now are the study's (or product's) own choices, named
   *  there; their analyte is named as the delivery names it (an id is never shown). */
  const pieceOf = (card: { tables: { values: Value[] }[] } | null | undefined) => {
    const values = (card?.tables ?? []).flatMap((t) => t.values)
      .filter((v) => v.file_sha256 === file.sha256 && link.targets.some((t) => v.id === t || v.id.startsWith(`${t}#`)));
    const base = linkedPiece(file.sha256, file.name, values);
    const analyte = base.own.analyte
      ? { id: base.own.analyte.id, label: analytes.find((a) => a.id === base.own.analyte!.id)?.label ?? base.own.analyte.label } : null;
    return { ...base, own: { arm: null, batch: null, analyte }, fileId: `elsewhere-${file.file_id}`, file: file.name, parts: [] };
  };
  const piece = pieceOf(now.data);
  const same = destinationKey(target) === destinationKey(was);
  const missing = targetProblem(target, analytes) ?? (same ? "It is linked there now: choose another place" : null);

  async function relink(why: string) {
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
      return;
    } finally {
      setChecking(false);
    }
    const clash = collisions([{ row: mine, target }], page!.subjects, held, analytes)[0];
    if (clash) {
      const text = `${file.name} holds ${clash.example}, which study ${clash.study} has in that arm already: in study ${clash.study} each file needs its own arm. Nothing was linked.`;
      setProblem(text);
      announce(text);
      return;
    }
    const sent = { ...target, analyte: analyteChoice(target.analyte, analyteChoices(analytes, mine.own.analyte, uses), analytes, mine.own.analyte) };
    const { data, problem: refused } = await decide(() => send("post", ASSIGN, { project_id: projectId }, assignBody(sent, link.targets, why)),
                                                    { refresh: false });
    if (data) {
      writePage(client, projectId, data);
      announce(`The ${plural(link.values, "value")} of ${file.name} are linked again: the earlier link to ${linkWords(link)} is replaced.`);
      onDone();
    } else setProblem(refused ?? "It was not linked.");
  }

  return (
    <div className="link-elsewhere" data-testid={`delivery-file-relink-form-${file.file_id}`}>
      <p className="muted fs-13 m-0">Linked now to {linkWords(link)}. Linking again replaces that link whole: its arm, batch and
        analyte are the ones chosen here.</p>
      <LinkEditor projectId={projectId} row={piece} target={target} onTarget={setTarget} subjects={page.subjects} analytes={analytes}
                  busy={busy || checking} missing={missing} suggestions={[]} onLink={relink} problem={problem} action="Link elsewhere"
                  used={(study) => (study === link.study ? analytesOf(now.data) : [])} />
      <button type="button" className="link-btn" onClick={onDone} data-testid={`delivery-file-relink-cancel-${file.file_id}`}>Cancel</button>
    </div>
  );
}
