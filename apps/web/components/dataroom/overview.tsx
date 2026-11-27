"use client";

// The Data room's Overview and Files (plan 2026-11-21 v2 §5 steps 3-5): the question card (confirmed or edited), four
// headline numbers, the sections with their dots, the conflicts first; every file with its type, pages, purpose and
// reason, scans read by OCR, turned pages and duplicates grouped.

import { useState } from "react";

import { PURPOSE, baseName, conflicts, fullCard, roleColour, type FileView, type NeedItem, type Problem, type QuestionCard as Card_, type Room, type Run } from "@/lib/dataroom";

import { useRoomActs } from "./acts";
import { Card, Dot, Nothing, Row, Sources, StatusTag, Table, usePaper } from "./kit";
import type { RoomStage } from "./layout";

const ROLES: Card_["products"][number]["role"][] = ["reference", "test", "original", "reformulated", "other"];

function QuestionForm({ card, onDone }: { card: Card_ | null; onDone: () => void }) {
  const acts = useRoomActs();
  const [draft, setDraft] = useState<Card_>(card ?? { question: "", regulator: "", approach: "", context_of_use: "", products: [],
                                                       checklist: [], quotes: [] });
  const [problem, setProblem] = useState<string | null>(null);
  const set = (k: "question" | "regulator" | "approach" | "context_of_use", v: string) => setDraft({ ...draft, [k]: v });
  const save = async (confirmed: boolean) => {
    const got = await acts!.question(draft, confirmed, confirmed ? "confirmed as edited" : "");
    if (got.problem) setProblem(got.problem); else onDone();
  };
  return (
    <form className="dr-form" onSubmit={(e) => { e.preventDefault(); void save(true); }} data-testid="question-form">
      <label className="dr-field"><span>What must the modelling answer?</span>
        <textarea rows={2} value={draft.question} onChange={(e) => set("question", e.target.value)} required data-testid="question-text" />
      </label>
      <div className="dr-form-row">
        <label className="dr-field"><span>For whom</span><input value={draft.regulator} onChange={(e) => set("regulator", e.target.value)} /></label>
        <label className="dr-field"><span>Approach</span><input value={draft.approach} onChange={(e) => set("approach", e.target.value)} /></label>
      </div>
      <label className="dr-field"><span>Context of use</span>
        <input value={draft.context_of_use} onChange={(e) => set("context_of_use", e.target.value)} /></label>
      <fieldset className="dr-field">
        <legend>Products compared</legend>
        {draft.products.map((p, i) => (
          <div key={i} className="dr-form-row">
            <input aria-label="Product" value={p.name} onChange={(e) => setDraft({ ...draft, products: draft.products.map((q, j) => j === i ? { ...q, name: e.target.value } : q) })} />
            <select aria-label="Role" value={p.role} onChange={(e) => setDraft({ ...draft, products: draft.products.map((q, j) => j === i ? { ...q, role: e.target.value as typeof p.role } : q) })}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <button type="button" className="btn small" onClick={() => setDraft({ ...draft, products: draft.products.filter((_q, j) => j !== i) })}>Remove</button>
          </div>
        ))}
        <button type="button" className="btn small" onClick={() => setDraft({ ...draft, products: [...draft.products, { name: "", role: "test", note: "" }] })}>Add a product</button>
      </fieldset>
      {draft.checklist.length > 0 && (
        <fieldset className="dr-field">
          <legend>Checklist ({draft.checklist.length})</legend>
          <ul className="dr-checklist">
            {draft.checklist.map((c) => (
              <li key={c.id}><span>{c.label}</span>
                <button type="button" className="btn small" onClick={() => setDraft({ ...draft, checklist: draft.checklist.filter((x) => x.id !== c.id) })}
                        aria-label={`Remove ${c.label}`}>Remove</button></li>
            ))}
          </ul>
        </fieldset>
      )}
      {problem && <div className="banner err" role="alert">{problem}</div>}
      <div className="dr-actions">
        <button type="submit" className="btn primary" disabled={acts?.busy || !draft.question.trim()}>Save and confirm</button>
        <button type="button" className="btn" disabled={acts?.busy || !draft.question.trim()} onClick={() => void save(false)}>Save as draft</button>
        {card && <button type="button" className="btn ghost" onClick={onDone}>Cancel</button>}
      </div>
    </form>
  );
}

export function QuestionCard({ room }: { room: Room }) {
  const card = room.question ? fullCard(room.question) : null;
  const acts = useRoomActs();
  const paper = usePaper();
  const [editing, setEditing] = useState(false);
  const [list, setList] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  if (editing || (!card && !paper && acts)) {
    return (
      <Card title="The question" testId="question-card">
        {!card && <p className="dr-lede">No question card yet: the question agent drafts it when it runs, or write it here.</p>}
        <QuestionForm card={card} onDone={() => setEditing(false)} />
      </Card>
    );
  }
  if (!card) return <Card title="The question"><Nothing>No question card yet.</Nothing></Card>;
  return (
    <Card title="The question" testId="question-card"
          aside={room.question_confirmed ? <span className="dr-tag ok" data-testid="question-confirmed">Confirmed</span>
                                         : <span className="dr-tag warn">Draft: confirm it</span>}>
      <p className="dr-question" data-testid="question-text-shown">{card.question}</p>
      <dl className="dr-facts">
        {card.regulator && <div><dt>For whom</dt><dd>{card.regulator}</dd></div>}
        {card.approach && <div><dt>Approach</dt><dd>{card.approach}</dd></div>}
        {card.context_of_use && <div className="wide"><dt>Context of use</dt><dd>{card.context_of_use}</dd></div>}
      </dl>
      {card.products.length > 0 && (
        <ul className="dr-products" aria-label="Products compared">
          {card.products.map((p) => (
            <li key={p.name}><span className="dr-swatch" style={{ background: roleColour(p.role) }} aria-hidden />
              <span>{p.name}<span className="muted"> · {p.role}</span></span></li>
          ))}
        </ul>
      )}
      {card.checklist.length > 0 && (paper ? (
        <ul className="dr-checklist">{card.checklist.map((c) => <li key={c.id}>{c.label}</li>)}</ul>
      ) : (
        <>
          <button type="button" className="dr-link" aria-expanded={list} onClick={() => setList(!list)}>
            {list ? "Hide" : "Show"} the checklist of {card.checklist.length} inputs
          </button>
          {list && <ul className="dr-checklist">{card.checklist.map((c) => <li key={c.id}>{c.label}{c.why && <span className="muted"> · {c.why}</span>}</li>)}</ul>}
        </>
      ))}
      {problem && <div className="banner err" role="alert">{problem}</div>}
      {acts && !paper && (
        <div className="dr-actions">
          {!room.question_confirmed && (
            <button type="button" className="btn primary" disabled={acts.busy} data-testid="question-confirm"
                    onClick={async () => { const got = await acts.question(card, true, "confirmed as drafted"); setProblem(got.problem); }}>
              Confirm
            </button>
          )}
          <button type="button" className="btn" onClick={() => setEditing(true)} data-testid="question-edit">Edit</button>
        </div>
      )}
    </Card>
  );
}

export function Headline({ room }: { room: Room }) {
  const read = room.files.filter((f) => f.state === "read" || f.state === "partly_read").length;
  const filled = room.inputs.filter((r) => r.status !== "missing").length;
  const tiles: [string, string, string][] = [
    ["files", String(read), read === 1 ? "file read" : "files read"],
    ["inputs", room.inputs.length ? `${filled} of ${room.inputs.length}` : "0", "inputs found"],
    ["requests", String(room.requests.filter((r) => r.status === "open").length), "data requests open"],
    ["decisions", String(room.decisions.filter((d) => !d.chosen && !d.on_inputs).length), "decisions waiting"],
  ];
  return (
    <div className="dr-tiles" data-testid="headline">
      {tiles.map(([id, v, l]) => <div key={id} className="dr-tile" data-testid={`headline-${id}`}><span className="v">{v}</span><span className="l">{l}</span></div>)}
    </div>
  );
}

const NEED_KIND: Record<NeedItem["kind"], [string, string]> = {
  question: ["info", "Question"], decision: ["warn", "Decide"], conflict: ["bad", "Settle"], check: ["warn", "Check"],
};

/** What needs a person first (plan 2026-11-26 §9, slice 5d), as code lists it (`room.needs_you`): the question, what
 *  holds an error, what disagrees, the checks to settle, then the decisions waiting. Each opens the one section where it
 *  is done. The population, sex and meal template are Inputs' (D1): said, not listed. */
function NeedsYou({ room, go }: { room: Room; go: (section: string) => void }) {
  const paper = usePaper();
  const items = room.needs_you ?? [];
  const onInputs = room.decisions.some((d) => d.on_inputs);
  const titles = new Map((room.layout ?? []).flatMap((g) => g.sections.map((s) => [s.id, s.title] as const)));
  const shown = paper ? items : items.slice(0, 10);
  return (
    <Card title="Needs you" testId="needs-you" aside={<span className="muted dr-small">Each opens where it is done</span>}>
      {items.length ? (
        <ul className="dr-list">
          {shown.map((n) => (
            <li key={n.id} className="dr-flag dr-need" data-testid={`need-${n.id}`} data-kind={n.kind}>
              <span className={`dr-tag ${n.severity === "error" ? "bad" : NEED_KIND[n.kind][0]} small`}>{NEED_KIND[n.kind][1]}</span>
              <span className="dr-need-body">
                <span><strong>{n.title}</strong>{(n.count ?? 1) > 1 ? <span className="muted"> ({n.count})</span> : null}</span>
                {n.detail && <span className="muted dr-small">{n.detail}</span>}
                {(n.sources ?? []).length > 0 && <Sources chips={n.sources ?? []} max={2} />}
              </span>
              {!paper && (
                <span className="dr-need-open">
                  <span className="muted dr-small">{titles.get(n.section) ?? ""}</span>
                  <button type="button" className="btn small" onClick={() => go(n.section)} data-testid={`need-open-${n.id}`}
                          aria-label={`Open ${titles.get(n.section) ?? "its section"}: ${n.title}`}>Open</button>
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : <p className="muted m-0" data-testid="needs-you-none">Nothing in this delivery waits for you.</p>}
      {!paper && items.length > shown.length && <p className="muted">and {items.length - shown.length} more, each in its section</p>}
      {onInputs && (
        <p className="muted dr-small m-0" data-testid="needs-you-inputs">The population, sex and meal template are chosen on Inputs: Clinical
          Study Design shows the delivery&apos;s facts behind them.</p>
      )}
    </Card>
  );
}

/** Before a file arrives (plan 2026-11-26 §9, slice 5c): each group, what it means, and what each of its sections will
 *  hold, each with nothing yet. */
function WillHold({ room, go }: { room: Room; go: (section: string) => void }) {
  return (
    <Card title="What you will see here" testId="overview-will-hold">
      <p className="muted dr-small m-0">Every file of the delivery is read and kept. What the model needs is checked, with its
        source, before it goes to Inputs.</p>
      {(room.layout ?? []).map((g) => (
        <div key={g.id} className="dr-sections-group" data-testid={`will-hold-${g.id}`}>
          <h4 className="dr-sections-group-title">{g.title}</h4>
          <p className="dr-small m-0-0-6">{g.meaning}</p>
          <ul className="dr-sections">
            {g.sections.map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => go(s.id)} data-testid={`will-hold-section-${s.id}`}>
                  <span className="dr-sections-title"><Dot status="empty" />{s.title}</span>
                  <span className="dr-sections-finding">{s.holds}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </Card>
  );
}

export function Overview({ room, go, stage = "read" }: { room: Room; go: (section: string) => void; stage?: RoomStage }) {
  const paper = usePaper();
  const first = conflicts(room);
  const reading = stage === "reading";
  if (stage === "empty" && !paper && (room.layout ?? []).length) {
    return <><QuestionCard room={room} /><WillHold room={room} go={go} /></>;
  }
  return (
    <>
      <QuestionCard room={room} />
      <Headline room={room} />
      {(room.layout ?? []).length > 0 && <NeedsYou room={room} go={go} />}
      {!(room.layout ?? []).length && first.length > 0 && (
        <Card title="Needs attention first" testId="overview-conflicts">
          <ul className="dr-list">
            {first.slice(0, paper ? undefined : 6).map((c, i) => (
              <li key={i} className="dr-flag" data-testid="conflict"><StatusTag status="conflict" />
                <span className="dr-flag-body"><span><strong>{c.label}</strong> · {c.detail}</span>{c.chips.length > 0 && <Sources chips={c.chips} />}</span></li>
            ))}
          </ul>
          {!paper && first.length > 6 && <p className="muted">and {first.length - 6} more in their sections</p>}
        </Card>
      )}
      {!paper && (room.layout ?? []).length > 0 && (
        <Card title="Sections" testId="overview-sections">
          {(room.layout ?? []).map((g) => (
            <div key={g.id} className="dr-sections-group" data-testid={`overview-group-${g.id}`}>
              <h4 className="dr-sections-group-title">{g.title}</h4>
              <ul className="dr-sections">
                {g.sections.map((s) => (
                  <li key={s.id}>
                    <button type="button" onClick={() => go(s.id)} data-testid={`overview-section-${s.id}`}>
                      <span className="dr-sections-title"><Dot status={s.status} reading={reading} />{s.title}</span>
                      <span className="dr-sections-finding">{s.finding || (s.count ? "" : reading ? "Fills in as the files are read"
                        : "Nothing in this delivery yet")}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </Card>
      )}
      {!paper && !(room.layout ?? []).length && (
        <Card title="Sections" testId="overview-sections">
          <ul className="dr-sections">
            {room.sections.map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => go(s.id)} data-testid={`overview-section-${s.id}`}>
                  <span className="dr-sections-title"><Dot status={s.status} />{s.title}</span>
                  <span className="dr-sections-finding">{s.finding}</span>
                </button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}

// --- files -----------------------------------------------------------------------------------------------------------

const KIND: Record<string, string> = {
  pdf: "PDF", docx: "Word", workbook: "Workbook", delimited: "Table (text)", text: "Text", image: "Image", archive: "Archive", other: "Other",
};

function pages(list: readonly number[]): string {
  const out: string[] = [];
  let i = 0;
  while (i < list.length) {
    let j = i;
    while (j + 1 < list.length && list[j + 1] === list[j] + 1) j++;
    out.push(j > i ? `${list[i]}–${list[j]}` : String(list[i]));
    i = j + 1;
  }
  return out.join(", ");
}

function Purpose({ file }: { file: FileView }) {
  const t = file.triage;
  if (file.duplicate_of) return <span className="dr-tag">Duplicate</span>;
  if (!t) return <span className="dr-tag quiet">Not sorted yet</span>;
  return <span className={`dr-tag ${t.purpose === "used" ? "ok" : t.purpose === "context" ? "info" : "quiet"}`}>{PURPOSE[t.purpose]}</span>;
}

function notes(file: FileView): string[] {
  const out: string[] = [];
  if (file.ocr_pages.length) out.push(`read by OCR: p. ${pages(file.ocr_pages)}`);
  if (file.turned_pages.length) out.push(`turned upright: p. ${pages(file.turned_pages)}`);
  if (file.duplicate_of) out.push(`same file as ${baseName(file.duplicate_of)}`);
  if (file.same_content_as) out.push(`same content as ${baseName(file.same_content_as)}`);
  if (file.state === "unreadable" || file.state === "unsupported") out.push(file.reason || "not read");
  if (file.state === "partly_read") out.push(`partly read${file.reason ? `: ${file.reason}` : ""}`);
  return out;
}

/** A check about a whole file, shown as a tag on its row (slice 5d). */
const FILE_TAG: Record<string, string> = { PERSONAL_DATA: "Personal data", FILE_NAMES_NOT_THE_DRUG: "Never names the drug" };

/** `checks`: the room's checks the layout places with the files (slice 5d); without a layout, every check (as before). */
export function Files({ room, run, checks }: { room: Room; run: Run | null; checks?: readonly Problem[] }) {
  // duplicates under the file they repeat, in the delivery's order
  const firsts = room.files.filter((f) => !f.duplicate_of);
  const ordered = firsts.flatMap((f) => [f, ...room.files.filter((d) => d.duplicate_of === f.path)]);
  const placed = checks ?? room.problems;
  const onFile = (path: string) => placed.filter((p) => FILE_TAG[p.code] && p.where?.file === path);
  const reading = placed.filter((p) => p.severity !== "info" && !(FILE_TAG[p.code] && p.where));
  const unsorted = run?.stages.find((s) => s.id === "triage")?.state === "skipped";
  if (!room.files.length) return <Nothing>No file is read yet: add the client&apos;s files and run.</Nothing>;
  return (
    <>
      <Card title={`${room.files.length} files`} testId="files-card"
            aside={unsorted ? <span className="muted dr-small">Not sorted: the sorting step has no AI model yet</span> : undefined}>
        <Table head={["File", "Pages", "Purpose", "Notes"]} label="The delivery's files" testId="files-table">
          {ordered.map((f) => (
            <Row key={f.path} testId={`file-row-${baseName(f.path)}`} cells={[
              <span key="n" className={`dr-file${f.duplicate_of ? " dup" : ""}`}><span className="dr-file-name">{f.name}</span>
                <span className="dr-file-kind">{KIND[f.kind] ?? f.kind}</span></span>,
              <span key="p" className="tnum">{f.pages || "—"}</span>,
              <Purpose key="u" file={f} />,
              <span key="o" className="dr-notes">
                {onFile(f.path).map((p) => <span key={p.code} className="dr-tag warn" data-testid={`file-check-${p.code}`}>{FILE_TAG[p.code]}</span>)}
                {f.ocr_pages.length > 0 && <span className="dr-tag info" data-testid="read-by-ocr">Read by OCR</span>}
                {notes(f).filter((n) => !n.startsWith("read by OCR")).join(" · ")}
              </span>,
            ]} details={(
              <dl className="dr-facts">
                <div className="wide"><dt>In the delivery</dt><dd>{f.path}</dd></div>
                {f.triage?.reason && <div className="wide"><dt>Why</dt><dd>{f.triage.reason}</dd></div>}
                {f.triage?.study && <div><dt>Study</dt><dd>{f.triage.study}</dd></div>}
                {notes(f).length > 0 && <div className="wide"><dt>Reading</dt><dd>{notes(f).join(" · ")}</dd></div>}
                {onFile(f.path).map((p) => <div key={p.code} className="wide"><dt>{FILE_TAG[p.code]}</dt><dd>{p.message}</dd></div>)}
              </dl>
            )} />
          ))}
        </Table>
      </Card>
      {reading.length > 0 && (
        <Card title="Reading checks" testId="reading-checks"
              aside={<span className="muted dr-small">What code refused or could not place, and why</span>}>
          <ul className="dr-list">
            {reading.slice(0, 12).map((p, i) => <li key={i}><span>{p.message}</span> {p.where && <Sources chips={[p.where]} />}</li>)}
          </ul>
          {reading.length > 12 && <p className="muted">and {reading.length - 12} more</p>}
        </Card>
      )}
    </>
  );
}
