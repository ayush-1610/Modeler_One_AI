"use client";

// A project's agent runs as a console table (P-19, the console redesign's slice 7), and one run's steps (P-19b). Read
// only. A run's numbers (turns, tokens, refusals) are the runtime's record of it, not a judgement of its answers.

import Link from "next/link";

import { Table } from "@/components/kit/Table";
import { Clip } from "@/components/kit/Clip";
import type { Schema } from "@/lib/api";
import { duration } from "@/lib/runs";

type Run = Schema<"AgentRunList">["runs"][number];
type Step = Record<string, unknown> & { seq?: number; kind?: string; at?: string; content?: Record<string, unknown> };

const STATUS_TONE: Record<string, string> = { COMPLETED: "low", RUNNING: "brand", FAILED: "high", ABORTED: "high" };
const when = (iso: string | null | undefined) => (iso ? iso.slice(0, 16).replace("T", " ") : "—");
const k = (n: number) => (n >= 10_000 ? `${Math.round(n / 1000)}k` : n.toLocaleString("en-US"));


export function AgentRunsTable({ runs, base }: { runs: Run[]; base: string }) {
  return (
    <Table caption="Agent runs" rows={runs} rowKey={(r) => r.run_id} rowTestId={(r) => `agent-run-${r.run_id}`} testId="agent-runs"
           filter={{ placeholder: "Filter runs (agent, model, who started it)", testId: "agent-runs-filter",
                     text: (r) => `${r.agent} ${r.agent_label ?? ""} ${r.model} ${r.provider ?? ""} ${r.started_by ?? ""} ${r.status}` }}
           columns={[
             { key: "agent", label: "Agent", sort: (r) => r.agent,
               render: (r) => <Link className="run-agent" href={`${base}/${encodeURIComponent(r.run_id)}`} prefetch={false}>{r.agent_label ?? r.agent}</Link> },
             { key: "model", label: "Model", sort: (r) => r.model,
               render: (r) => <>{r.model}{r.fallback_from && <div className="muted fs-12" data-testid={`agent-run-fallback-${r.run_id}`}>after {r.fallback_from}</div>}</> },
             { key: "who", label: "Started by", sort: (r) => r.started_by ?? "",
               render: (r) => (r.started_by ? <span className="nowrap">{r.started_by}</span> : <span className="muted">no one (automatic)</span>) },
             { key: "started", label: "Started", sort: (r) => r.started_at, render: (r) => <span className="nowrap">{when(r.started_at)}</span> },
             { key: "took", label: "Took", render: (r) => <span className="nowrap">{duration(r.started_at, r.finished_at)}</span> },
             { key: "status", label: "Status", sort: (r) => r.status,
               render: (r) => <span className={`chip ${STATUS_TONE[r.status] ?? "neutral"}`}>{r.status.toLowerCase()}</span> },
             { key: "turns", label: "Turns", num: true, sort: (r) => r.turns, render: (r) => r.turns },
             { key: "tokens", label: "Tokens in / out", num: true, sort: (r) => r.input_tokens + r.output_tokens,
               render: (r) => `${k(r.input_tokens)} / ${k(r.output_tokens)}` },
             { key: "refusals", label: "Refused calls", num: true, sort: (r) => r.refusals,
               render: (r) => (r.refusals ? <span className="chip medium">{r.refusals}</span> : "0") },
           ]}
           empty="No agent has run on this project yet. Agents run when they are switched on and a step asks for one." />
  );
}

const KIND_WORD: Record<string, string> = {
  model_turn: "the model answered", tool_result: "a tool answered", tool_call_rejected: "a tool call refused",
  model_switch: "switched model", finish_reminder: "reminded to finish", context_fitted: "context shortened",
  conversation_restarted: "conversation restarted", llm_unavailable: "no model available", mcp_tool_call: "an outside tool called",
  mcp_tool_skipped: "an outside tool skipped",
};

/** What one step says, in a line: the model's tool calls or text, a tool's name, the refusal, the switch. */
function said(step: Step): string {
  const c = (step.content ?? {}) as Record<string, unknown>;
  if (step.kind === "model_turn") {
    const calls = Array.isArray(c.tool_calls) ? (c.tool_calls as { name?: string }[]).map((t) => t.name).filter(Boolean) : [];
    return calls.length ? `calls ${calls.join(", ")}` : String(c.content ?? "").trim() || "(no text)";
  }
  if (step.kind === "tool_result") return `${String(c.tool ?? "")}: ${typeof c.result === "string" ? c.result : JSON.stringify(c.result ?? "")}`;
  if (step.kind === "tool_call_rejected") return String(c.error ?? "");
  if (step.kind === "model_switch") return `${String(c.from ?? "")} → ${String(c.to ?? "")}${c.why ? ` (${String(c.why)})` : ""}`;
  return Object.entries(c).filter(([key]) => key !== "type" && key !== "turn").map(([key, v]) => `${key}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(" · ");
}

export function RunSteps({ steps }: { steps: Step[] }) {
  return (
    <Table caption="The run's steps" rows={steps} rowKey={(s) => String(s.seq)} rowTestId={(s) => `run-step-${s.seq}`} testId="run-steps"
           filter={{ placeholder: "Filter steps", text: (s) => `${s.kind ?? ""} ${said(s)}` }}
           columns={[
             { key: "seq", label: "#", num: true, sort: (s) => Number(s.seq ?? 0), render: (s) => s.seq },
             { key: "turn", label: "Turn", num: true, render: (s) => String((s.content as Record<string, unknown> | undefined)?.turn ?? "—") },
             { key: "at", label: "When", render: (s) => <span className="nowrap">{String(s.at ?? "").slice(11, 19)}</span> },
             { key: "kind", label: "Step", sort: (s) => s.kind ?? "",
               render: (s) => <span className={s.kind === "tool_call_rejected" || s.kind === "llm_unavailable" ? "chip medium" : undefined}>
                 {KIND_WORD[s.kind ?? ""] ?? (s.kind ?? "").replace(/_/g, " ")}</span> },
             { key: "said", label: "What", render: (s) => <Clip text={said(s)} /> },
           ]}
           empty="This run recorded no step." />
  );
}
