"use client";

import { useState } from "react";

import { InlineIssue } from "@/components/kit";
import { Block } from "@/components/start/Blocks";
import { Seg, Source, ValueInput } from "@/components/start/FieldRow";
import type { BriefView, FieldDef } from "@/lib/brief";
import { defOf, GATE_STATE, recordOf, valueOf, type Gate, type Open, type Save } from "@/lib/start";

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

/** The routes of the scenarios, one row each (route and food state), which the routes gate reads. */
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
          <span className="muted route-dose">{valueOf(view, `scenarios[${i}].dose`) ? `${valueOf(view, `scenarios[${i}].dose`)} mg` : ""}</span>
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

/** Block 4 (D-28): what is being modelled, asked before any data work. Anything the builder cannot model is refused
 *  here as "not supported yet", instead of failing at S0 or S3. */
export function ScopeGates({ view, save, open }: { view: BriefView; save: Save; open: Open }) {
  const gates = Object.fromEntries(view.start.gates.map((g) => [g.gate, g])) as Record<Gate["gate"], Gate>;
  const one = (gate: Gate) => {
    const def = defOf(view, gate.path);
    const record = recordOf(view, gate.path);
    return (
      <div key={gate.gate} className={`gate ${gate.state}`} data-testid={`gate-${gate.gate}`}>
        <GateHead gate={gate} />
        <div className="gate-body">
          <Pick key={record.at ?? ""} path={gate.path} options={def.options} labels={def.option_labels}
                stored={valueOf(view, gate.path)} save={save} testId={`pick-${gate.gate}`} />
          <Source record={record} open={open} />
          <GateNote gate={gate} />
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
        {one(gates.modality)}
        {one(gates.pbpk_model)}
        {one(gates.site_of_action)}
        <div className={`gate ${forms.state}`} data-testid="gate-formulation_types">
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
          </div>
        </div>
        <div className={`gate ${gates.routes.state}`} data-testid="gate-routes">
          <GateHead gate={gates.routes} />
          <div className="gate-body">
            <Routes view={view} save={save} />
            <GateNote gate={gates.routes} />
          </div>
        </div>
      </div>
    </Block>
  );
}
