"use client";

// The Delivery section on Inputs (contracts 2026-11-12 §8.10): what arrived from the client, read by code and reviewed
// by exception. The coverage panel says how much of each file was read (its regions, the numeric cells no mapping used,
// the numbers outside every table, the values with no study stated) and how long each stage took; under it, what to
// ask the client for, the mappings that wait for a person, the "study not stated" values, and each study, product and
// the compound with its card. The section is not shown while the pipeline is off (`enabled` false); it reads again
// every few seconds while a file is being read.

import { useEffect, useRef, useState } from "react";

import { send } from "@/lib/api";
import { useRefresh, useResource } from "@/lib/hooks";

import { MappingReview } from "./MappingReview";
import {
  ChipFor, FILE_STATE, KIND_LABEL, MAPPING_STATE, Problem, REGION_STATE, WITHHELD, Why, fieldText, levelText, plural, useDecide, when,
  type FileRow, type Page, type Region, type SubjectRow,
} from "./shared";
import { SubjectCard } from "./SubjectCard";
import { Unassigned } from "./Unassigned";

const RUN = "/api/v1/projects/{project_id}/delivery:run" as const;
const EXCLUDE = "/api/v1/projects/{project_id}/delivery/regions:exclude" as const;
type Decide = ReturnType<typeof useDecide>["decide"];

/** The decision's scope for a region of this kind: a table's numbers leave silent loss only as a region. */
const scopeOf = (r: Region) => (r.kind === "prose" ? "unread_prose" : r.kind === "figure" ? "figures" : "regions");

function coverageLine(f: FileRow): string {
  const c = f.coverage;
  if (!c) return "";
  return [`${plural(c.regions, "region")}: ${c.regions_mapped} read, ${c.regions_excluded} set aside, ${c.regions_unread} not read`,
          `silent loss ${c.silent_loss}`, `${plural(c.outside_numeric, "number")} outside every table`,
          `${plural(c.values_unassigned, "value")} with no study`,
          c.needs_ocr_pages.length ? `${plural(c.needs_ocr_pages.length, "page")} need OCR` : "",
          c.anchors_unresolved ? `${plural(c.anchors_unresolved, "place")} not found again` : ""].filter(Boolean).join(" · ");
}

function FileItem({ projectId, file, first, decide, busy, onMapping }: {
  projectId: string; file: FileRow;
  /** a repeat's regions are listed on the first arrival of the same bytes */
  first: FileRow | undefined; decide: Decide; busy: boolean; onMapping: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [aside, setAside] = useState<string | null>(null);
  const shown = file.repeat && first ? first : file;
  const exclude = (regions: string[], scope: "regions" | "unread_prose" | "figures" | "outside") => async (why: string) => {
    const { data } = await decide(() => send("post", EXCLUDE, { project_id: projectId }, { file_sha256: file.sha256, regions, scope, why }));
    if (data) setAside(null);
  };
  return (
    <li className="delivery-file" data-testid={`delivery-file-${file.file_id}`} data-state={file.state}>
      <div className="delivery-file-line">
        <ChipFor state={file.state} table={FILE_STATE} testId={`delivery-file-state-${file.file_id}`} />
        <span className="delivery-file-name">{file.name}</span>
        {file.container && <span className="muted">in {file.container.name}</span>}
        {file.repeat && <span className="chip neutral">the same file arrived before</span>}
        {file.blinded && <span className="chip neutral" data-testid={`delivery-file-blinded-${file.file_id}`}>holds a blinded study</span>}
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)} data-testid={`delivery-file-toggle-${file.file_id}`}>
          {open ? "Hide its regions" : "Show its regions"}</button>
        <button type="button" className="btn tiny" disabled={busy} aria-label={`Read ${file.name} again`} data-testid={`delivery-file-run-${file.file_id}`}
                onClick={() => void decide(() => send("post", RUN, { project_id: projectId }, { files: [file.sha256] }))}>Read again</button>
      </div>
      {file.reason && <p className="delivery-file-why" data-testid={`delivery-file-reason-${file.file_id}`}>{file.reason}</p>}
      {file.coverage && <p className="muted fs-13 m-0" data-testid={`delivery-file-coverage-${file.file_id}`}>{coverageLine(file)}</p>}
      {file.legacy_refusal && <p className="muted fs-13 m-0">Not read onto the cards below: {file.legacy_refusal}</p>}
      {file.run?.state === "failed" && file.run.error && <p className="delivery-file-why">{file.run.error}</p>}
      {open && (
        <div className="delivery-file-detail">
          {shown.regions.length > 0 ? (
            <div className="table-scroll">
              <table className="delivery-regions" data-testid={`delivery-regions-${file.file_id}`}>
                <caption className="sr-only">The regions of {file.name}</caption>
                <thead><tr><th>Where</th><th>What</th><th>State</th><th>Mapping</th><th className="num">Numeric cells</th><th /></tr></thead>
                <tbody>
                  {shown.regions.map((r) => (
                    <tr key={r.region_id} data-testid={`delivery-region-${r.region_id}`}>
                      <td><code>{r.where}</code></td>
                      <td>{fieldText(r.kind)}{r.table_kind && r.table_kind !== "unknown" ? `, ${fieldText(r.table_kind)}` : ""}
                        <div className="muted fs-12">{r.caption === null ? WITHHELD : r.caption}</div></td>
                      <td><ChipFor state={r.state} table={REGION_STATE} />{r.reason && <div className="muted fs-12">{r.reason}</div>}</td>
                      <td>
                        {r.mapping_id ? (
                          <button type="button" className="delivery-chip-btn" onClick={() => onMapping(r.mapping_id as string)}
                                  data-testid={`delivery-region-mapping-${r.region_id}`} title="Review how this table is read">
                            <ChipFor state={r.mapping_status} table={MAPPING_STATE} /> v{r.mapping_version}{r.origin ? ` · ${fieldText(r.origin)}` : ""}
                          </button>
                        ) : null}
                      </td>
                      <td className="num">{r.numeric_cells ? `${r.used} used · ${r.excluded} set aside · ${r.silent} silent` : ""}</td>
                      <td>
                        {r.state !== "excluded" && r.state !== "waiting" && aside !== r.region_id && (
                          <button type="button" className="link-btn" onClick={() => setAside(r.region_id)} data-testid={`delivery-region-aside-${r.region_id}`}>Not data…</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p className="muted m-0">No region was found in this file.</p>}
          {shown.regions.filter((r) => r.region_id === aside).map((r) => (
            <Why key={r.region_id} action="Set it aside as not data" label={`Why ${r.where} is not data`} busy={busy} onCancel={() => setAside(null)}
                 testId="delivery-region-aside" onSubmit={exclude([r.region_id], scopeOf(r))}>
              <span className="muted">{r.where}: what was read from it is set aside too.</span>
            </Why>
          ))}
          {shown.outside.length > 0 && (
            <>
              <h4 className="delivery-sub">Text with a number outside every table</h4>
              <ul className="delivery-plain">
                {shown.outside.map((o) => (
                  <li key={o.where} className={o.counted ? "delivery-check open" : "delivery-check"}>
                    <div className="delivery-check-line">
                      <span className={`chip ${o.counted ? "high" : "neutral"}`}>{o.counted ? "not read" : "accounted for"}</span>
                      <span className="delivery-check-text">“{o.text ?? WITHHELD}” <span className="muted">{o.where}{o.region ? " · read with its table" : ""}</span></span>
                    </div>
                    {o.counted && <Why action="It is not data" label="Why this text is not data" busy={busy} testId="delivery-file-outside-accept"
                                       onSubmit={exclude([o.where], "outside")} />}
                  </li>
                ))}
              </ul>
            </>
          )}
          {file.run && file.run.stages.length > 0 && (
            <>
              <h4 className="delivery-sub">How long each stage took <span className="muted">run {file.run.attempt}, {when(file.run.finished_at ?? file.run.started_at ?? file.run.queued_at)}</span></h4>
              <ul className="delivery-stages" data-testid={`delivery-stages-${file.file_id}`}>
                {file.run.stages.map((s) => (
                  <li key={s.stage} className={s.ok ? undefined : "failed"} title={s.detail}>
                    <strong>{fieldText(s.stage)}</strong> {s.seconds < 0.01 ? "< 0.01" : s.seconds.toFixed(2)} s
                    <span className="muted"> {s.detail}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </li>
  );
}

function confirmationChip(s: SubjectRow) {
  const c = s.confirmation;
  if (!c) return <span className="chip medium">to review</span>;
  if (!c.current) return <span className="chip medium">changed since it was confirmed</span>;
  return c.landed ? <span className="chip low">confirmed and loaded</span> : <span className="chip medium">signed, not loaded yet</span>;
}

function Coverage({ page }: { page: Page }) {
  const t = page.totals;
  const states = Object.entries(t.files_by_state).map(([state, n]) => `${n} ${FILE_STATE[state]?.label ?? fieldText(state)}`).join(", ");
  const tiles: [string, number, string, string][] = [
    ["files", t.files, t.files === 1 ? "file" : "files", states],
    ["regions", t.regions, t.regions === 1 ? "region" : "regions", `${t.regions_mapped} read, ${t.regions_excluded} set aside, ${t.regions_unread} not read`],
    ["silent-loss", t.silent_loss, "silent loss", "numeric cells of a table that no mapping used or set aside"],
    ["outside", t.outside_numeric, "numbers outside every table", "text with a number that belongs to no table"],
    ["unassigned", t.values_unassigned, "values with no study stated", "read, but no label says whose they are"],
    ["values", t.values, "values in the ledger", "what was read and is active"],
  ];
  if (t.needs_ocr_pages) tiles.push(["ocr", t.needs_ocr_pages, "pages need OCR", "scanned pages no text was read from"]);
  if (t.anchors_unresolved) tiles.push(["anchors", t.anchors_unresolved, "places not found again", "a value whose place in its file no longer resolves"]);
  return (
    <dl className="delivery-tiles" data-testid="delivery-coverage">
      {tiles.map(([id, n, label, note]) => (
        <div key={id} className={n > 0 && ["silent-loss", "outside", "unassigned", "ocr", "anchors"].includes(id) ? "delivery-tile warn" : "delivery-tile"}>
          <dd data-testid={`delivery-total-${id}`}>{n}</dd>
          <dt>{label}<span className="muted">{note}</span></dt>
        </div>
      ))}
    </dl>
  );
}

export function DeliverySection({ projectId }: { projectId: string }) {
  const read = useResource("/api/v1/projects/{project_id}/delivery", { project_id: projectId }, { poll: (d) => d.running, interval: 3000 });
  const { decide, busy, problem } = useDecide();
  const refresh = useRefresh();
  const [folded, setFolded] = useState(false);
  const [subject, setSubject] = useState<string | null>(null);
  const [mapping, setMapping] = useState<string | null>(null);
  const [asked, setAsked] = useState(false);
  const was = useRef(false);
  const page = read.data;
  const running = page?.running ?? false;

  // a file read while the page is open brings values onto the cards: every resource is read again when the reading ends
  useEffect(() => {
    if (running) was.current = true;
    else if (was.current) { was.current = false; void refresh(); }
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!page) return read.problem ? <section className="delivery"><Problem text={`The delivery review could not be read: ${read.problem}`} /></section> : null;
  if (!page.enabled) return null;

  const files = page.deliveries.flatMap((d) => d.files);
  const first = new Map<string, FileRow>();
  for (const f of files) if (!f.repeat && !first.has(f.sha256)) first.set(f.sha256, f);
  const t = page.totals;
  const summary = files.length
    ? [`${plural(t.files, "file")}`, `${t.regions_mapped} of ${plural(t.regions, "region")} read`, `silent loss ${t.silent_loss}`,
       `${plural(t.outside_numeric, "number")} outside every table`, `${plural(t.values_unassigned, "value")} with no study`].join(" · ")
    : "no client file has arrived yet";

  return (
    <section className={`delivery${page.mappings.length || page.unassigned.length ? " waits" : ""}`} data-testid="delivery-section">
      <div className="delivery-head">
        <strong>Delivery review</strong>
        <span className="muted" data-testid="delivery-counts" role="status" aria-live="polite">{summary}</span>
        {running && <span className="chip medium" data-testid="delivery-running">reading the files…</span>}
        <span className="chip neutral" data-testid="delivery-rules" title={`intake rules, sha256 ${page.rules.sha256}`}>rules {page.rules.status} v{page.rules.version}</span>
        {files.length > 0 && (
          <span className="delivery-head-actions">
            <button type="button" className="btn tiny" disabled={busy || running} data-testid="delivery-run"
                    onClick={() => void decide(() => send("post", RUN, { project_id: projectId }, { files: [] }))}>Read again</button>
            <button type="button" className="link-btn" aria-expanded={!folded} onClick={() => setFolded(!folded)} data-testid="delivery-toggle">
              {folded ? "Show the review" : "Hide the review"}</button>
          </span>
        )}
      </div>
      <Problem text={problem} testId="delivery-problem" />
      {files.length > 0 && !folded && (
        <div className="delivery-body">
          <Coverage page={page} />

          <section className="delivery-block" data-testid="delivery-files">
            <div className="delivery-block-head"><h3>What arrived</h3></div>
            {page.deliveries.map((d) => (
              <div key={d.id} data-testid={`delivery-arrival-${d.id}`}>
                <p className="muted fs-12 m-0">Delivery {d.id} · {when(d.at)} · {d.by}</p>
                <ul className="delivery-plain">
                  {d.files.map((f) => <FileItem key={f.file_id} projectId={projectId} file={f} first={first.get(f.sha256)} decide={decide} busy={busy} onMapping={setMapping} />)}
                </ul>
              </div>
            ))}
          </section>

          {page.request.length > 0 && (
            <section className="delivery-block" data-testid="delivery-request">
              <div className="delivery-block-head">
                <h3>Still to ask the client for</h3>
                <span className="chip neutral">{plural(page.request.length, "item")}</span>
                <button type="button" className="link-btn" aria-expanded={asked} onClick={() => setAsked(!asked)} data-testid="delivery-request-toggle">
                  {asked ? "Hide them" : "Show them"}</button>
              </div>
              {asked && (
                <ul className="delivery-plain">
                  {page.request.map((line, i) => (
                    <li key={`${line.req_id}-${i}`}>
                      <span className={`chip ${line.required ? "high" : "neutral"}`}>{line.required ? "required" : "useful"}</span>{" "}
                      {line.what} <span className="muted">· {line.why}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {page.mappings.length > 0 && (
            <section className="delivery-block" data-testid="delivery-mappings">
              <div className="delivery-block-head"><h3>How a table is read waits for you</h3><span className="chip medium">{plural(page.mappings.length, "mapping")}</span></div>
              <ul className="delivery-plain">
                {page.mappings.map((m) => (
                  <li key={`${m.mapping_id}-${m.version}`} className="delivery-check open" data-testid={`delivery-mapping-${m.mapping_id}`}>
                    <div className="delivery-check-line">
                      <ChipFor state={m.status} table={MAPPING_STATE} />
                      <span className="delivery-check-text">{fieldText(m.kind)} table, version {m.version}, proposed by {m.origin === "llm" ? "the table mapper" : m.origin === "rule" ? "a rule" : "a person"}:
                        {" "}{m.used_in.map((u) => `${u.file} ${u.where}`).join("; ") || "not in use"}</span>
                      {m.waiting && <span className="chip medium">being read again</span>}
                      <button type="button" className="btn tiny" onClick={() => setMapping(m.mapping_id)} data-testid={`delivery-mapping-open-${m.mapping_id}`}>Review…</button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <Unassigned projectId={projectId} page={page} />

          <section className="delivery-block" data-testid="delivery-subjects">
            <div className="delivery-block-head"><h3>To review and confirm</h3></div>
            {page.subjects.length === 0 && <p className="muted m-0">No study, product or compound value was read yet.</p>}
            <ul className="delivery-plain">
              {page.subjects.map((s) => {
                const open = subject === `${s.subject_type}/${s.subject}`;
                return (
                  <li key={`${s.subject_type}/${s.subject}`} className={open ? "delivery-subject open" : "delivery-subject"} data-testid={`delivery-subject-${s.subject}`}>
                    <div className="delivery-subject-line">
                      <button type="button" className="delivery-subject-name" aria-expanded={open} data-testid={`delivery-subject-open-${s.subject}`}
                              onClick={() => setSubject(open ? null : `${s.subject_type}/${s.subject}`)}>
                        <span className="muted">{KIND_LABEL[s.subject_type]}</span> {s.label}
                      </button>
                      <span className="muted">{plural(s.values, "value")}{Object.keys(s.by_level).length ? `: ${Object.entries(s.by_level).map(([l, n]) => `${n} ${levelText(l)}`).join(", ")}` : ""}</span>
                      {confirmationChip(s)}
                      {s.blinded && <span className="chip neutral">blinded</span>}
                      {s.confirm_on === "client-review" && <span className="chip neutral">confirmed on its own card</span>}
                      {s.loaded_elsewhere.length > 0 && <span className="chip neutral">loaded from its own card</span>}
                    </div>
                    {open && <SubjectCard projectId={projectId} row={s} deliveries={page.deliveries} onMapping={setMapping} />}
                  </li>
                );
              })}
            </ul>
          </section>
        </div>
      )}
      {mapping && <MappingReview projectId={projectId} mappingId={mapping} onClose={() => setMapping(null)} />}
    </section>
  );
}
