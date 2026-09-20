// A real renal compound (Aciclovir) prefilled for the guided flow, so a new project can be run end-to-end
// immediately. The CPF is S0-complete (physchem + GFR elimination) and the study carries an observed IV
// plasma profile; deterministic NCA on the backend turns it into the observed PK the acceptance gate reads.

export const ACICLOVIR_CPF = {
  compound: "Aciclovir",
  parameters: [
    { id: "phys.mw", value: 225.2, unit: "g/mol", status: "FIXED",
      provenance: { source_type: "measured", reference: "OSP Aciclovir model" } },
    { id: "phys.logp", value: -1.56, unit: "Log Units", status: "FIXED",
      provenance: { source_type: "measured", reference: "OSP Aciclovir model" } },
    { id: "phys.pka.neutral", value: 1.0, status: "FIXED",
      provenance: { source_type: "assumed", reference: "neutral across pH 6.5-7.4" } },
    { id: "bind.fu", value: 0.85, status: "FIXED",
      provenance: { source_type: "measured", reference: "OSP Aciclovir model" } },
    { id: "phys.solubility.ref", value: 1.3, unit: "mg/ml", status: "FIXED",
      provenance: { source_type: "measured", reference: "OSP Aciclovir model" } },
    { id: "elim.renal.gfr_fraction", value: 1.0, status: "FIXED",
      provenance: { source_type: "measured", reference: "unbound glomerular filtration" } },
  ],
};

export const ACICLOVIR_STUDIES = [
  {
    study_id: "iv",
    reference: "IV bolus 250 mg, healthy adults",
    route: "iv_bolus",
    dose_mg: 250,
    infusion_time_min: 5,
    formulation: "solution",
    food_state: "fasted",
    n: 12,
    n_timepoints: 8,
    profile: {
      times: [5, 15, 30, 60, 120, 240, 360, 480],
      values: [45.2, 33.1, 24.0, 15.2, 7.1, 2.3, 0.9, 0.35],
      time_unit: "min",
      unit: "µmol/l",
    },
  },
];
