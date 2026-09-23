"""Twelve end-to-end case studies covering different drugs, routes, applications and failure modes.

Each case is driven through the real HTTP API exactly as a user would drive the UI: create the project, put
the CPF, upload observed studies, generate and sign the MAP, start the campaign, watch it run. Several cases
are *expected* to fail or escalate — the guardrails are as much under test as the happy path.
"""
from __future__ import annotations

# ---- CPF building blocks -------------------------------------------------------------------------

def _p(pid, value, unit=None, status="FIXED", source="Publication", reference="reference value",
       fit=None, plaus=None, binding=None):
    rec = {"id": pid, "value": value, "status": status,
           "provenance": {"source_type": source, "reference": reference}}
    if unit:
        rec["unit"] = unit
    if fit:
        rec["fit_policy"] = {"stage": fit[0], "lower": fit[1], "upper": fit[2]}
    if plaus:
        rec["plausibility"] = {"lower": plaus[0], "upper": plaus[1], "source": plaus[2]}
    if binding:
        rec["engine_binding"] = binding
    return rec


GFR_BINDING = {"building_block": "Compound", "parameter": "GFR fraction",
               "process": "GlomerularFiltration", "data_source": "Literature"}


def renal_cpf(compound, *, mw, logp, fu, sol=1.3, gfr=1.0, fittable=True):
    """A renally-cleared compound: filtration is bound to the engine so it actually clears."""
    params = [
        _p("phys.mw", mw, "g/mol"),
        _p("phys.logp", logp, "Log Units",
           fit=(["S1"], logp - 1.5, logp + 1.5) if fittable else None,
           plaus=(logp - 1.5, logp + 1.5, "measured logP +/- 1.5 [SME]") if fittable else None),
        _p("phys.pka.base.0", 2.27),
        _p("phys.pka.acid.0", 9.25),
        _p("bind.fu", fu),
        _p("phys.solubility.ref", sol, "mg/ml"),
        _p("elim.renal.gfr_fraction", gfr, status="PREDICTED", source="assumed",
           reference="apparent net renal clearance (filtration + tubular secretion, lumped)",
           binding=GFR_BINDING,
           fit=(["S1"], 0.0, 3.0) if fittable else None,
           plaus=(0.0, 3.0, "MS-01 2.2 GFR fraction range [SME]") if fittable else None),
    ]
    return {"compound": compound, "parameters": params}


def hepatic_cpf(compound, *, mw, logp, fu, enzyme="CYP3A4", clspec=0.05):
    """A hepatically-cleared compound. The metabolism process needs an expression profile to act in a real
    PK-Sim run — the platform should say so rather than quietly producing a model that cannot clear."""
    binding = {"building_block": "Compound", "parameter": "CLspec/[Enzyme]",
               "process": f"MetabolizationSpecific_FirstOrder:{enzyme}", "data_source": "InVitro"}
    return {"compound": compound, "parameters": [
        _p("phys.mw", mw, "g/mol"),
        _p("phys.logp", logp, "Log Units", fit=(["S1"], logp - 1.5, logp + 1.5)),
        _p("phys.pka.base.0", 5.5),
        _p("bind.fu", fu),
        _p("phys.solubility.ref", 0.2, "mg/ml"),
        _p(f"elim.hepatic.{enzyme}.clspec", clspec, "l/µmol/min", binding=binding,
           fit=(["S1", "S2"], 1e-4, 1e2), plaus=(1e-4, 1e2, "OSP library range [SME]")),
    ]}


def profile(times, values, unit="µmol/l"):
    return {"times": times, "values": values, "time_unit": "min", "unit": unit}


def iv_study(study_id, dose_mg, prof, *, infusion_min=60, reference="illustrative"):
    return {"study_id": study_id, "reference": reference, "route": "iv_infusion", "dose_mg": dose_mg,
            "infusion_time_min": infusion_min, "formulation": "solution", "food_state": "fasted",
            "n": 12, "n_timepoints": len(prof["times"]), "profile": prof}


def oral_study(study_id, dose_mg, prof, *, reference="illustrative"):
    return {"study_id": study_id, "reference": reference, "route": "oral", "dose_mg": dose_mg,
            "formulation": "solution", "food_state": "fasted", "n": 12,
            "n_timepoints": len(prof["times"]), "profile": prof}


# ---- observed data, synthesised from the stand-in at KNOWN true parameter values -----------------
#
# Generating the observed profiles from the same analytical model the platform will simulate gives every case
# a ground truth: we know the parameter value the fit is supposed to recover, so "did it converge?" has a
# checkable answer. A case whose true value equals the CPF's starting value should pass immediately; a case
# whose true value differs must be diagnosed and fitted back.

import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
from analytical_engine import concentrations as _concentrations

T = [5, 15, 30, 60, 90, 120, 180, 240, 360, 480, 720]


def synth(*, mw, logp, fu, dose_mg, times=None, gfr=0.0, clspec=0.0, route="iv", infusion_min=60, noise=0.0):
    """The profile the model produces for these true parameters (optionally roughened by a fixed factor)."""
    times = list(times or T)
    model = {"mw": mw, "logp": logp, "fu": fu, "gfr_fraction": gfr, "clspec": clspec,
             "route": route, "dose_mg": dose_mg, "infusion_min": infusion_min, "times_min": times}
    values = [round(v * (1.0 + noise), 4) for v in _concentrations(model)]
    return profile(times, values)


ACI = {"mw": 225.2, "logp": -1.56, "fu": 0.85}
# truth == the CPF's starting point: the model is already right, so the gate should pass on round 1
ACICLOVIR_ON = synth(**ACI, dose_mg=250, gfr=1.0)
# truth is a compound that clears twice as fast as the CPF assumes: a genuine clearance misfit the loop must fit
ACICLOVIR_FAST = synth(**ACI, dose_mg=250, gfr=2.0)
# a uniform concentration offset with an unchanged half-life (a volume error, not a clearance error)
# 0.6 puts the ratio at ~1.67: outside the medium tier (1.5-fold) but inside the low tier (2-fold),
# so the pair of tier cases differs only in the risk rating — which is the point being demonstrated.
ACICLOVIR_FLAT_OFFSET = profile(T, [round(v * 0.6, 4) for v in ACICLOVIR_ON["values"]])
SPARSE = synth(**ACI, dose_mg=250, gfr=1.0, times=[60, 480])
ORAL_PROFILE = synth(**ACI, dose_mg=400, gfr=1.0, route="oral")
HEPATIC_ON = synth(mw=410.5, logp=3.2, fu=0.08, dose_mg=100, clspec=0.05)
FAST_ON = synth(mw=180.0, logp=-0.5, fu=0.95, dose_mg=100, gfr=2.5)


CASES = [
    {
        "id": "01-aciclovir-fih",
        "title": "Aciclovir — first-in-human renal starting dose",
        "application": "FIH translation",
        "narrative": "The baseline: a renally cleared antiviral with one IV infusion study. Everything the "
                     "model needs is present and the observed data agree with the model.",
        "compound": "Aciclovir", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [iv_study("iv-250mg", 250, ACICLOVIR_ON)],
        "expect": "S0 and S1 pass — the reference happy path.",
    },
    {
        "id": "02-aciclovir-misfit",
        "title": "Aciclovir — model disagrees with the data, must fit its way back",
        "application": "FIH translation",
        "narrative": "Same compound, but the real drug clears twice as fast as the CPF assumes, so the model "
                     "over-predicts exposure and the half-life is wrong too. The loop must diagnose clearance "
                     "and fit it back — the true answer is a GFR fraction of 2.0.",
        "compound": "Aciclovir", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [iv_study("iv-250mg", 250, ACICLOVIR_FAST)],
        "expect": "Round 1 fails the gate; diagnostics pick a clearance fit; a later round passes or escalates.",
    },
    {
        "id": "03-hepatic-cyp3a4",
        "title": "Hepatically cleared compound (CYP3A4)",
        "application": "Exposure prediction",
        "narrative": "A lipophilic compound cleared by CYP3A4 rather than the kidney. PK-Sim needs an enzyme "
                     "expression profile for this process to act — the platform should not pretend otherwise.",
        "compound": "Hepatidrug", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": hepatic_cpf("Hepatidrug", mw=410.5, logp=3.2, fu=0.08),
        "studies": [iv_study("iv-100mg", 100, HEPATIC_ON)],
        "expect": "Builds and runs, and surfaces the expression-profile limitation as a note.",
    },
    {
        "id": "04-incomplete-cpf",
        "title": "Incomplete CPF — no elimination pathway at all",
        "application": "Readiness check",
        "narrative": "A half-filled parameter framework. MS-01 says a campaign may not start until the S0 "
                     "readiness gate is satisfied, so this must be refused rather than run.",
        "compound": "Halfdrug", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": {"compound": "Halfdrug", "parameters": [
            _p("phys.mw", 300.0, "g/mol"), _p("phys.logp", 1.0, "Log Units"), _p("bind.fu", 0.2),
        ]},
        "studies": [iv_study("iv-50mg", 50, synth(**ACI, dose_mg=50, gfr=1.0))],
        "expect": "S0 readiness fails and the campaign stops before any engine run.",
    },
    {
        "id": "05-unbound-clearance",
        "title": "Clearance present in the CPF but not bound to the engine",
        "application": "Guardrail",
        "narrative": "The CPF declares renal clearance but gives the builder no engine binding for it. Before "
                     "this was caught, the model silently came out with no clearance at all.",
        "compound": "Silentdrug", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": {"compound": "Silentdrug", "parameters": [
            _p("phys.mw", 225.2, "g/mol"), _p("phys.logp", -1.5, "Log Units"), _p("phys.pka.acid.0", 9.2),
            _p("bind.fu", 0.85), _p("phys.solubility.ref", 1.3, "mg/ml"),
            _p("elim.renal.gfr_fraction", 1.0),  # deliberately no engine_binding
        ]},
        "studies": [iv_study("iv-250mg", 250, ACICLOVIR_ON)],
        "expect": "The build reports the parameter as NOT PLACED IN THE MODEL instead of dropping it silently.",
    },
    {
        "id": "06-no-observed-data",
        "title": "No observed data uploaded",
        "application": "Guardrail",
        "narrative": "A project with a complete CPF but nothing to compare against. There is nothing to fit or "
                     "validate, so the campaign must not be preparable.",
        "compound": "Aciclovir", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [],
        "expect": "Preparing the campaign is refused with a clear reason.",
    },
    {
        "id": "07-high-risk-tier",
        "title": "High model risk — the strict 1.25-fold acceptance tier",
        "application": "Dose selection (high impact)",
        "narrative": "Identical data to the baseline, but the question carries high model risk. ICH M15 then "
                     "demands agreement within 1.25-fold on every study.",
        "compound": "Aciclovir", "model_risk": "high", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [iv_study("iv-250mg", 250, ACICLOVIR_FLAT_OFFSET)],
        "expect": "The same model that would pass at medium risk is held to a stricter bar.",
    },
    {
        "id": "08-low-risk-tier",
        "title": "Low model risk — the 2-fold acceptance tier",
        "application": "Exploratory support",
        "narrative": "The mirror image: the same off-model data judged against the low-risk 2-fold tier, where "
                     "a rougher agreement is acceptable for the decision being supported.",
        "compound": "Aciclovir", "model_risk": "low", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [iv_study("iv-250mg", 250, ACICLOVIR_FLAT_OFFSET)],
        "expect": "Acceptance depends on the tier, not on the modeller — the same data, a different verdict.",
    },
    {
        "id": "09-oral-absorption",
        "title": "Oral dosing — the absorption stage",
        "application": "Oral exposure",
        "narrative": "An oral solution rather than an infusion, which exercises the absorption stage (S2) and "
                     "the oral scenario builder.",
        "compound": "Aciclovir", "model_risk": "medium", "stages": ["S0", "S1", "S2"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [iv_study("iv-250mg", 250, ACICLOVIR_ON), oral_study("po-400mg", 400, ORAL_PROFILE)],
        "expect": "S1 trains on the IV study, S2 on the oral one.",
    },
    {
        "id": "10-multi-study-split",
        "title": "Several studies — internal versus external split",
        "application": "Model qualification",
        "narrative": "Three studies across two dose levels. MS-01 splits them deterministically into a fitting "
                     "set and a held-out validation set, and records why.",
        "compound": "Aciclovir", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [
            iv_study("iv-250mg", 250, ACICLOVIR_ON),
            iv_study("iv-500mg", 500, synth(**ACI, dose_mg=500, gfr=1.0)),
            iv_study("iv-125mg", 125, synth(**ACI, dose_mg=125, gfr=1.0)),
        ],
        "expect": "Studies are assigned INTERNAL/EXTERNAL deterministically and the split is recorded in the MAP.",
    },
    {
        "id": "11-sparse-data",
        "title": "Sparse observed data — only two timepoints",
        "application": "Data-poor setting",
        "narrative": "Real programmes often have very little data. Two points is not enough for a terminal "
                     "half-life, so the tool should degrade gracefully rather than invent one.",
        "compound": "Aciclovir", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Aciclovir", mw=225.2, logp=-1.56, fu=0.85),
        "studies": [iv_study("iv-sparse", 250, SPARSE)],
        "expect": "Runs, with NCA reporting what two points can and cannot support.",
    },
    {
        "id": "12-high-clearance",
        "title": "High-clearance compound — a different PK shape",
        "application": "Exposure prediction",
        "narrative": "A rapidly cleared, highly unbound compound, to confirm the pipeline is genuinely driven "
                     "by the parameter framework rather than replaying one canned curve.",
        "compound": "Fastdrug", "model_risk": "medium", "stages": ["S0", "S1"],
        "cpf": renal_cpf("Fastdrug", mw=180.0, logp=-0.5, fu=0.95, gfr=2.5),
        "studies": [iv_study("iv-100mg", 100, FAST_ON)],
        "expect": "A visibly faster profile than the baseline compound.",
    },
]
