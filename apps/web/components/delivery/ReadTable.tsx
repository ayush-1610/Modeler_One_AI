"use client";

// "Read this table…" (plan 2026-11-14 §3 API 4): a table no layout reads (never read, or its layout was rejected) gets
// its first layout from a person, written in the layout form and sent to `POST /delivery/mappings:propose`. The form
// shows the table's first rows as the page gives them (`DeliveryRegion.head`: its header only, digits masked, for a file
// that holds a blinded study's values) and names each column by its header; its words are the API's own
// (`GET /delivery/vocabulary`), so a project where no table has a layout yet gets the form too. Code checks the layout on
// this table before anything is stored: a layout that does not read the table comes back with its findings, each shown
// beside the column it names (masked for a file that holds a blinded study's values, as the API gives them). Stored, it
// waits for approval like any other layout, and the file is read again with it.

import { useState } from "react";

import { Dialog } from "@/components/kit/Dialog";
import { send } from "@/lib/api";
import { useResource } from "@/lib/hooks";

import { LayoutEditor, columnsSent, type Finding } from "./LayoutEditor";
import { whereIs } from "@/lib/words";
import { Problem, WITHHELD, fieldText, useDecide, type FileRow, type Region } from "./shared";

const PROPOSE = "/api/v1/projects/{project_id}/delivery/mappings:propose" as const;
const VOCABULARY = "/api/v1/projects/{project_id}/delivery/vocabulary" as const;

/** Whether a table can be given a first layout here: a table no layout reads now (never read, or its layout rejected). */
export const readable = (r: Region) => r.kind === "table" && (r.state === "unread" || r.mapping_status === "rejected");

/** The dialog that gives `region` of `file` its first layout. `onStored`: the new layout's mapping, to review it. */
export function ReadTable({ projectId, file, region, onClose, onStored }: {
  projectId: string; file: FileRow; region: Region; onClose: () => void; onStored: (mappingId: string) => void;
}) {
  const words = useResource(VOCABULARY, { project_id: projectId });
  const ready = words.data !== null || words.problem !== null;
  const { decide, busy, problem } = useDecide();
  const [findings, setFindings] = useState<Finding[]>([]);
  const [sent, setSent] = useState<number[]>([]);
  const place = whereIs(region.where);
  const head = region.head;
  // the table's first guess: what the rules took it for (if they could tell; else the person chooses), the header rows
  // code finds (one when its first rows are not given), the data under them
  const kind = region.table_kind && region.table_kind !== "unknown" ? region.table_kind : "";
  const headerRows = head?.header_rows ?? 1;
  const guess = { schema: "mapping/2", kind, layout: "long", header_rows: headerRows, first_data_row: headerRows + 1 };

  async function propose(spec: Record<string, unknown>, why: string): Promise<boolean> {
    setSent(columnsSent(spec));
    let found: Finding[] = [];
    const { data } = await decide(async () => {
      const env = await send("post", PROPOSE, { project_id: projectId }, { file_sha256: file.sha256, region_id: region.region_id, spec, why });
      found = (env.errors[0]?.detail?.findings as Finding[] | undefined) ?? [];
      return env;
    });
    setFindings(found);
    if (data) onStored(data.mapping_id);
    return Boolean(data);
  }

  return (
    <Dialog title="Read this table" size="wide" onClose={onClose} testId="read-table-dialog">
      <div className="delivery-mapping" data-testid={`read-table-${region.region_id}`}>
        <p className="m-0">
          <strong>{place.place}</strong> of {file.name}
          {region.caption ? <span className="muted"> · “{region.caption}”</span> : region.caption === null ? <span className="muted"> · {WITHHELD}</span> : null}
          <span className="muted"> · {region.state === "unread" ? "no layout reads it yet" : "its layout was rejected"}
            {region.table_kind && region.table_kind !== "unknown" ? ` · looks like a ${fieldText(region.table_kind)} table` : ""}</span>
        </p>
        <p className="muted m-0">Say what each column holds. Code checks the layout on this table before anything is stored, and
          says beside a column what does not fit. The layout then waits for approval like any other, and the file is read
          again with it.{!head && " The table's cells could not be read here: its file's row in Client files opens its sheets."}</p>
        {!ready && <p className="muted m-0">Reading the layout words…</p>}
        {ready && !words.data && (
          <p className="muted m-0" data-testid="read-table-text-only">The form&apos;s choices could not be read ({words.problem}): write the
            layout as text.</p>
        )}
        {ready && (
          <LayoutEditor vocabulary={words.data} spec={guess} columns={head?.n_cols ?? place.columns ?? 0} head={head} start={place.start}
                        findings={findings} sent={sent} busy={busy} action="Read the table with this layout"
                        whyLabel="Why the table reads this way" onSubmit={propose} onCancel={onClose} testId="read-table" />
        )}
        <Problem text={problem} testId="read-table-problem" />
      </div>
    </Dialog>
  );
}
