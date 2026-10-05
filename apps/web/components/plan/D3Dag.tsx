"use client";

import { useMemo, useRef, useState } from "react";

import { ROLE_LABEL, type OverallStudy, type PlanView, type Role, violationsFor } from "@/lib/plan";

// D3 · development and validation DAG (plan §11.4). Nodes are stages; the datasets placed on them are chips. A dataset
// (from "Overall Data" or another node) dropped on a node, on the arrow leading into it, or on the training layer is a
// proposed placement: the server's validator answers first, then the person gives the reason and confirms.

export const STUDY_MIME = "application/x-modeler-study";
const NODE_MIME = "application/x-modeler-node";
const W = 960;
const H = 740;

type NodeId = "S1" | "S2" | "S3" | "S4" | "S5" | "S6" | "SUPPORTIVE";
type NodeSpec = { id: NodeId; title: string; sub: string; role: Role | null; w: number; h: number; x: number; y: number };

const DEFAULT_NODES: NodeSpec[] = [
  { id: "S1", title: "S1 · IV", sub: "trains distribution and elimination", role: "S1", w: 290, h: 190, x: 16, y: 40 },
  { id: "S2", title: "S2 · oral fasted", sub: "trains absorption", role: "S2", w: 290, h: 190, x: 335, y: 40 },
  { id: "S3", title: "S3 · formulation / fed", sub: "trains release and fed effects", role: "S3", w: 290, h: 190, x: 654, y: 40 },
  { id: "S4", title: "S4 · internal validation", sub: "every training study, final CPF", role: null, w: 760, h: 74, x: 100, y: 280 },
  { id: "S5", title: "S5 · external validation", sub: "judged, never fitted", role: "S5", w: 760, h: 92, x: 100, y: 390 },
  { id: "S6", title: "S6 · application", sub: "DDI · PGx · special populations · preclinical", role: "S6", w: 760, h: 74, x: 100, y: 508 },
  { id: "SUPPORTIVE", title: "Supportive", sub: "context only", role: "SUPPORTIVE", w: 760, h: 74, x: 100, y: 610 },
];
// The CPF flows along these edges; dropping a dataset on an edge places it on the edge's target.
const EDGES: [NodeId, NodeId][] = [["S1", "S2"], ["S2", "S3"], ["S3", "S4"], ["S4", "S5"], ["S5", "S6"]];
// Where a dataset dropped on the training layer (not on a node) trains, by its MS-01 class; the validator has the last word.
const TRAINS: Record<string, Role> = { "IV-SD": "S1", "PO-SOL-FASTED": "S2", "PO-IR-FASTED": "S2", "PO-FED": "S3" };

export function StudyChip({ s, view, compact = false }: { s: OverallStudy; view: PlanView; compact?: boolean }) {
  const issues = violationsFor(view, s.study_id);
  const level = issues.some((v) => v.severity === "error") ? "err" : issues.some((v) => !v.acknowledged) ? "warn" : "";
  const test = ["SYNTHETIC", "ILLUSTRATIVE", "UNRECORDED"].includes(s.origin);
  return (
    <div className={`study-chip ${level}`} draggable data-testid={`chip-${s.study_id}`}
         onDragStart={(e) => { e.dataTransfer.setData(STUDY_MIME, s.study_id); e.dataTransfer.setData("text/plain", s.study_id);
                               e.dataTransfer.effectAllowed = "move"; }}
         title={[s.rationale && `Why: ${s.rationale}`, s.reason && `Placed: ${s.reason}`, ...issues.map((v) => v.message)]
           .filter(Boolean).join("\n")}>
      <span className="sq">■</span>
      <span className="sid">{s.study_id}</span>
      {!compact && <span className="muted">{s.study_class}</span>}
      <span className={`origin ${test ? "test" : ""}`}>{s.origin.toLowerCase().replace("_", " ")}</span>
      {s.userLocked && <span className="lock" title={`placed by a person: ${s.reason}`}>🔒</span>}
      {s.new && <span className="chip medium">new</span>}
      {!s.evaluable && <span className="muted" title="no profile: not judged by the campaign">NCA</span>}
    </div>
  );
}

export function D3Dag({ view, onDrop, onLayout }: {
  view: PlanView;
  onDrop: (studyId: string, role: Role, where: string) => void;
  onLayout: (layout: Record<string, { x: number; y: number }>) => void;
}) {
  const canvas = useRef<HTMLDivElement | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const nodes = useMemo(() => DEFAULT_NODES.map((n) => ({ ...n, ...(view.plan.layout[n.id] ?? {}) })), [view.plan.layout]);
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n])) as Record<NodeId, NodeSpec>;
  const studies = view.overall_data.studies;
  const trained = studies.filter((s) => ["S1", "S2", "S3"].includes(s.role));

  const accept = (e: React.DragEvent) => {
    if (e.dataTransfer.types.includes(STUDY_MIME) || e.dataTransfer.types.includes(NODE_MIME)) e.preventDefault();
  };
  const dropStudy = (role: Role | null, where: string) => (e: React.DragEvent) => {
    const sid = e.dataTransfer.getData(STUDY_MIME);
    setOver(null);
    if (!sid) return;
    e.preventDefault();
    e.stopPropagation();
    const study = studies.find((s) => s.study_id === sid);
    const target = role ?? (study ? TRAINS[study.study_class] ?? "S2" : null);
    if (study && target && target !== study.role) onDrop(sid, target, where);
  };
  const dropOnCanvas = (e: React.DragEvent) => {
    const node = e.dataTransfer.getData(NODE_MIME);
    if (!node || !canvas.current) return;
    e.preventDefault();
    const [id, dx, dy] = node.split("|");
    const rect = canvas.current.getBoundingClientRect();
    const scale = rect.width / W;
    const x = Math.round((e.clientX - rect.left) / scale - Number(dx));
    const y = Math.round((e.clientY - rect.top) / scale - Number(dy));
    onLayout({ ...view.plan.layout, [id]: { x: Math.max(0, Math.min(W - 60, x)), y: Math.max(0, Math.min(H - 40, y)) } });
  };

  const anchor = (a: NodeSpec, b: NodeSpec) => {
    const horizontal = Math.abs(a.y - b.y) < 40;
    const from = horizontal ? { x: a.x + a.w, y: a.y + a.h / 2 } : { x: a.x + a.w / 2, y: a.y + a.h };
    const to = horizontal ? { x: b.x, y: b.y + b.h / 2 } : { x: b.x + b.w / 2, y: b.y };
    return { from, to, mid: { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 } };
  };

  return (
    <div className="dag-scroll">
      <div className="dag" ref={canvas} style={{ width: W, height: H }} onDragOver={accept} onDrop={dropOnCanvas}
           data-testid="d3-canvas">
        <div className={`dag-layer${over === "layer" ? " over" : ""}`} style={{ left: 6, top: 8, width: W - 12, height: 236 }}
             onDragOver={(e) => { accept(e); setOver("layer"); }} onDragLeave={() => setOver(null)}
             onDrop={dropStudy(null, "the training layer")} data-testid="layer-training">
          <span className="dag-layer-label">training layer · fitted S1 → S3</span>
        </div>
        <svg className="dag-edges" viewBox={`0 0 ${W} ${H}`} width={W} height={H} aria-hidden>
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" className="dag-arrowhead" />
            </marker>
          </defs>
          {EDGES.map(([a, b]) => {
            const { from, to } = anchor(byId[a], byId[b]);
            return <path key={`${a}-${b}`} d={`M ${from.x} ${from.y} L ${to.x} ${to.y}`} className="dag-edge" markerEnd="url(#arrow)" />;
          })}
        </svg>
        {EDGES.map(([a, b]) => {
          const target = byId[b];
          if (!target.role) return null;
          const { mid } = anchor(byId[a], target);
          return (
            <div key={`h-${a}-${b}`} className={`edge-handle${over === `edge-${a}-${b}` ? " over" : ""}`}
                 style={{ left: mid.x - 11, top: mid.y - 11 }} title={`drop here: ${ROLE_LABEL[target.role]}`}
                 data-testid={`edge-${a}-${b}`}
                 onDragOver={(e) => { accept(e); setOver(`edge-${a}-${b}`); }} onDragLeave={() => setOver(null)}
                 onDrop={dropStudy(target.role, `the ${a} → ${b} arrow`)} />
          );
        })}
        {nodes.map((n) => {
          const here = n.id === "S4" ? trained : studies.filter((s) => s.role === n.role);
          const fits = Object.entries(view.plan.fits).filter(([, f]) => f.stages.includes(n.id));
          return (
            <div key={n.id} className={`dag-node ${n.id === "S4" ? "derived" : ""}${over === n.id ? " over" : ""}`}
                 style={{ left: n.x, top: n.y, width: n.w, minHeight: n.h }} data-testid={`node-${n.id}`}
                 onDragOver={n.role ? (e) => { accept(e); setOver(n.id); } : undefined}
                 onDragLeave={n.role ? () => setOver(null) : undefined}
                 onDrop={n.role ? dropStudy(n.role, n.title) : undefined}>
              <div className="dag-node-head" draggable
                   onDragStart={(e) => {
                     const rect = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
                     const scale = rect.width / n.w;
                     e.dataTransfer.setData(NODE_MIME, `${n.id}|${Math.round((e.clientX - rect.left) / scale)}|${Math.round((e.clientY - rect.top) / scale)}`);
                   }}
                   title="drag to move the node (the layout is saved with the plan)">
                <strong>{n.title}</strong>
                <span className="muted">{n.sub}{view.plan.budgets[n.id] ? ` · ${Math.round(view.plan.budgets[n.id] / 60)} min` : ""}</span>
              </div>
              <div className="dag-chips">
                {here.map((s) => n.id === "S4"
                  ? <span key={s.study_id} className="study-chip ghost">■ {s.study_id}</span>
                  : <StudyChip key={s.study_id} s={s} view={view} compact />)}
                {here.length === 0 && <span className="muted" style={{ fontSize: 12 }}>{n.role ? "drop datasets here" : "nothing trained"}</span>}
              </div>
              {fits.length > 0 && (
                <div className="dag-fits">fits {fits.map(([pid, f]) => <code key={pid} title={f.reason}>{pid} [{f.lower}, {f.upper}]</code>)}</div>
              )}
              {n.role && ["S1", "S2", "S3"].includes(n.role) && (view.plan.fit_candidates[n.role]?.length ?? 0) > 0 && fits.length === 0 && (
                <div className="dag-fits muted">MS-01 candidates: {view.plan.fit_candidates[n.role].join(", ")} (none freed)</div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
