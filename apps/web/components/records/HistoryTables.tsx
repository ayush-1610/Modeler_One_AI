"use client";

// History's two lists of events (P-21, the console redesign's slice 7), as console tables with a text filter and
// sortable heads: the project's audit trail (`GET /audit`) and its signatures (`GET /signatures`, R-N09, which holds
// the decisions on its campaigns' escalations the audit trail's filter leaves out). Read only: nothing is decided here.

import { Table } from "@/components/kit/Table";
import { Clip } from "@/components/kit/Clip";
import type { Schema } from "@/lib/api";

type AuditEvent = Schema<"AuditTrail">["events"][number];
type Signature = Schema<"SignatureRegister">["signatures"][number];

const when = (iso: string) => iso.slice(0, 19).replace("T", " ");

export function AuditTable({ events, projectId }: { events: AuditEvent[]; projectId: string }) {
  const own = (id: string) => (id.startsWith(`${projectId}/`) ? id.slice(projectId.length + 1) : id);
  return (
    <Table caption="Audit trail" rows={events} rowKey={(e) => String(e.seq)} rowTestId={(e) => `audit-${e.seq}`} testId="audit-table"
           filter={{ placeholder: "Filter events (who, action, record, reason)", testId: "audit-filter",
                     text: (e) => `${e.actor} ${e.action} ${e.resource_type} ${e.resource_id} ${e.reason ?? ""}` }}
           columns={[
             { key: "seq", label: "#", num: true, sort: (e) => e.seq, render: (e) => e.seq },
             { key: "when", label: "When", sort: (e) => e.occurred_at, render: (e) => <span className="nowrap">{when(e.occurred_at)}</span> },
             { key: "who", label: "Who", sort: (e) => e.actor, render: (e) => e.actor },
             { key: "action", label: "Action", sort: (e) => e.action, render: (e) => <code>{e.action}</code> },
             { key: "record", label: "Record", sort: (e) => `${e.resource_type}:${e.resource_id}`,
               render: (e) => <code>{e.resource_type}:{own(e.resource_id)}</code> },
             { key: "reason", label: "Reason", render: (e) => <Clip text={e.reason} /> },
           ]}
           empty="No events yet." />
  );
}

const MEANING_TONE: Record<string, string> = { Approved: "low", Reviewed: "brand", Authored: "neutral" };

export function SignatureTable({ signatures }: { signatures: Signature[] }) {
  return (
    <Table caption="Signatures" rows={signatures} rowKey={(s) => `${s.seq}-${s.signature_id}`} rowTestId={(s) => `signature-${s.signature_id}`}
           testId="signature-table"
           filter={{ placeholder: "Filter signatures (signer, meaning, record)", testId: "signature-filter",
                     text: (s) => `${s.printed_name ?? ""} ${s.signer_id} ${s.meaning} ${s.record_type} ${s.record_id}` }}
           columns={[
             { key: "when", label: "Signed", sort: (s) => s.signed_at, render: (s) => <span className="nowrap">{when(s.signed_at)}</span> },
             { key: "who", label: "Signer", sort: (s) => s.printed_name ?? s.signer_id,
               render: (s) => <>{s.printed_name ?? s.signer_id}{s.printed_name && <span className="muted fs-12"> · {s.signer_id}</span>}</> },
             { key: "meaning", label: "Meaning", sort: (s) => s.meaning,
               render: (s) => <span className={`chip ${MEANING_TONE[s.meaning] ?? "neutral"}`}>{s.meaning}</span> },
             { key: "record", label: "Record", sort: (s) => `${s.record_type} ${s.record_id}`,
               render: (s) => <><span className="muted">{s.record_type.replace(/[-_]/g, " ")}</span> <code>{s.record_id}</code></> },
             { key: "hash", label: "Record hash", render: (s) => <code title={s.record_sha256}>{s.record_sha256.slice(0, 12)}…</code> },
             { key: "id", label: "Signature", render: (s) => <code>{s.signature_id}</code> },
           ]}
           empty="No signature on this project's records yet." />
  );
}
