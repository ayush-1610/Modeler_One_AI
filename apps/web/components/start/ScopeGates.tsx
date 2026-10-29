"use client";

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Block } from "@/components/start/Blocks";
import { NeedsYou, Seg, Source, ValueInput } from "@/components/start/FieldRow";
import type { BriefView, FieldDef } from "@/lib/brief";
import { defOf, GATE_STATE, recordOf, valueOf, type Gate, type Marks, type Open, type Save } from "@/lib/start";

function GateHead({ gate }: { gate: Gate }) {
  const state = GATE_STATE[gate.state];
  return (
    <div className="gate-head">
      <span className="sb-label">{gate.label}</span>
      <span className={`chip ${state.tone}`} data-testid={`gate-${gate.gate}-state`}>{state.label}</span>
    </div>
  );
}

function GateNote({ gate }: { gate: Gate }) {
  if (gate.state === "not_supported") {
    return <InlineIssue severity="error" testId={`gate-${gate.gate}-message`}>{gate.message}. The builder makes {gate.supported}; support is added one product type at a time, with the SME.</InlineIssue>;
  }
  if (gate.state === "limited") return <InlineIssue testId={`gate-${gate.gate}-message`}>{gate.message}</InlineIssue>;
  return <p className="gate-supported muted">The builder makes {gate.supported}.</p>;
}

/** A one-of choice shown as chosen at once, then saved (the server's answer replaces it, keyed by the record's time). */
function Pick({ path, options, labels, stored, save, testId }: {
  path: string; options: string[]; labels: Record<string, string>; stored: unknown; save: Save; testId: string;
}) {
  const [value, setValue] = useState<unknown>(stored);
  return <Seg options={options} labels={labels} value={value} testId={testId}
              onPick={(v) => { setValue(v); void save([{ path, status: "EDITED", value: v }]); }} />;
}

/** The formulation types, ticked at once and saved as a whole (none ticked clears the field). */
function Formulations({ def, stored, save }: { def: FieldDef; stored: unknown; save: Save }) {
  const [value, setValue] = useState<unknown>(stored);
  const path = "scope.formulation_types";
  return <ValueInput def={def} value={value} testId="pick-formulation_types" onChange={(v) => {
    setValue(v);
    void save([Array.isArray(v) && v.length ? { path, status: "EDITED", value: v } : { path, status: "MISSING" }]);
  }} />;
}

/** A scenario's dose, edited where its route is (page review 1: it was in the notes). */
function Dose({ path, index, stored, save }: { path: string; index: number; stored: number | null; save: Save }) {
  const [text, setText] = useState(stored == null ? "" : String(stored));
  const changed = text.trim() !== (stored == null ? "" : String(stored));
  return (
    <span className="route-dose">
      <input type="number" min={0} step="any" value={text} aria-label={`Dose of scenario ${index + 1} (mg)`} style={{ width: 90 }}
             data-testid={`dose-${index}`} onChange={(e) => setText(e.target.value)}
             onBlur={() => changed && save([text.trim() ? { path, status: "EDITED", value: Number(text) } : { path, status: "MISSING" }])} />
      <span className="muted"> mg</span>
    </span>
  );
}

/** The routes of the scenarios, one row each (route, food state and dose), which the routes gate reads. */
function Routes({ view, save }: { view: BriefView; save: Save }) {
  const items = view.brief.groups.scenarios ?? [];
  const [adding, setAdding] = useState(false);
  const routeDef = defOf(view, "scenarios[0].route");
  const foodDef = defOf(view, "scenarios[0].food_state");
  const label = (v: unknown) => (v ? String(v).replace(/_/g, " ") : "—");
  return (
    <div className="route-rows" data-testid="start-routes">
      {items.map((_, i) => (
        <div key={i} className="route-row">
          <span className="muted">{i + 1}</span>
          <select aria-label={`Route of scenario ${i + 1}`} value={String(valueOf(view, `scenarios[${i}].route`) ?? "")}
                  data-testid={`route-${i}`}
                  onChange={(e) => e.target.value && save([{ path: `scenarios[${i}].route`, status: "EDITED", value: e.target.value }])}>
            <option value="">—</option>
            {routeDef.options.map((o) => <option key={o} value={o}>{label(o)}</option>)}
          </select>
          <select aria-label={`Food state of scenario ${i + 1}`} value={String(valueOf(view, `scenarios[${i}].food_state`) ?? "")}
                  onChange={(e) => e.target.value && save([{ path: `scenarios[${i}].food_state`, status: "EDITED", value: e.target.value }])}>
            <option value="">food state —</option>
            {foodDef.options.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
          <Dose key={recordOf(view, `scenarios[${i}].dose`).at ?? ""} path={`scenarios[${i}].dose`} index={i}
                stored={valueOf(view, `scenarios[${i}].dose`) as number | null} save={save} />
        </div>
      ))}
      {adding ? (
        <div className="route-row">
          <span className="muted">{items.length + 1}</span>
          <select aria-label="Route of the new scenario" defaultValue="" data-testid="route-new"
                  onChange={async (e) => {
                    if (!e.target.value) return;
                    const refused = await save([{ path: `scenarios[${items.length}].route`, status: "EDITED", value: e.target.value }]);
                    if (!refused) setAdding(false);
                  }}>
            <option value="">choose the route</option>
            {routeDef.options.map((o) => <option key={o} value={o}>{label(o)}</option>)}
          </select>
        </div>
      ) : (
        <button type="button" className="btn" data-testid="route-add" onClick={() => setAdding(true)}>Add a route</button>
      )}
    </div>
  );
}

const PRODUCT = ["modality", "pbpk_model", "site_of_action"] as const;

/** Block 4 (D-28): what is being modelled, asked before any data work. Anything the builder cannot model is refused
 *  here as "not supported yet", instead of failing at S0 or S3. Modality, PBPK model and site of action read as one line
 *  ("small molecule · full PBPK · systemic"); their choices open on Change, or by themselves when one is not set or not
 *  supported (page review 1). A box that waits on the person is marked red. */
export function ScopeGates({ view, save, open, marks }: { view: BriefView; save: Save; open: Open; marks: Marks }) {
  const gates = Object.fromEntries(view.start.gates.map((g) => [g.gate, g])) as Record<Gate["gate"], Gate>;
  const [opened, setOpened] = useState(false);
  const product = PRODUCT.map((g) => gates[g]);
  const expanded = opened || product.some((g) => g.state !== "supported");
  const productLine = product.map((g) => {
    const v = valueOf(view, g.path);
    return v ? (defOf(view, g.path).option_labels[String(v)] ?? String(v).replace(/_/g, " ")) : "not set";
  }).join(" · ");
  const one = (gate: Gate) => {
    const def = defOf(view, gate.path);
    const record = recordOf(view, gate.path);
    return (
      <div key={gate.gate} className={`gate ${gate.state}${marks.issues(gate.path).length ? " needs-you" : ""}`}
           data-testid={`gate-${gate.gate}`}>
        <GateHead gate={gate} />
        <div className="gate-body">
          <Pick key={record.at ?? ""} path={gate.path} options={def.options} labels={def.option_labels}
                stored={valueOf(view, gate.path)} save={save} testId={`pick-${gate.gate}`} />
          <Source record={record} open={open} />
          <GateNote gate={gate} />
          <NeedsYou issues={marks.issues(gate.path)} />
        </div>
      </div>
    );
  };
  const forms = gates.formulation_types;
  const formsDef = defOf(view, "scope.formulation_types");
  const formsRecord = recordOf(view, "scope.formulation_types");
  return (
    <Block n={4} title="What is modelled" testId="start-scope"
           lede="Modality, model type, site of action, formulation and routes. What the builder cannot model yet is said here, before any data is gathered.">
      <div className="gates">
        {expanded ? product.map(one) : (
          <div className="gate supported" data-testid="gate-product">
            <div className="gate-head">
              <span className="sb-label">What is built</span>
              <button type="button" className="btn sb-change" data-testid="gate-product-change" onClick={() => setOpened(true)}>Change</button>
            </div>
            <span className="sb-text" data-testid="gate-product-line">{productLine}</span>
          </div>
        )}
        <div className={`gate ${forms.state}${marks.issues("scope.formulation_types").length ? " needs-you" : ""}`}
             data-testid="gate-formulation_types">
          <GateHead gate={forms} />
          <div className="gate-body">
            <Formulations key={formsRecord.at ?? ""} def={formsDef}
                          stored={formsRecord.status === "NOT_APPLICABLE" ? [] : formsRecord.value} save={save} />
            <label className="gate-na">
              <input type="checkbox" checked={formsRecord.status === "NOT_APPLICABLE"} data-testid="formulation-none"
                     onChange={(e) => save([{ path: "scope.formulation_types", status: e.target.checked ? "NOT_APPLICABLE" : "MISSING" }])} />
              {" "}None: intravenous only
            </label>
            <Source record={formsRecord} open={open} />
            <GateNote gate={forms} />
            <NeedsYou issues={marks.issues("scope.formulation_types")} />
          </div>
        </div>
        <div className={`gate ${gates.routes.state}${marks.issues(gates.routes.path).length ? " needs-you" : ""}`}
             data-testid="gate-routes">
          <GateHead gate={gates.routes} />
          <div className="gate-body">
            <Routes view={view} save={save} />
            <GateNote gate={gates.routes} />
            <NeedsYou issues={marks.issues(gates.routes.path)} />
          </div>
        </div>
      </div>
    </Block>
  );
}
