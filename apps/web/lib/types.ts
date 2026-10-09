// The shapes the read APIs return, mirroring the backend domain models. This file used to carry sample data that
// pages showed whenever a read failed; that hid real faults behind made-up numbers, so it holds types only now.

import type { Rating, Schema } from "@/lib/api";

// The project, its questions and a compound's CPF view are typed by the API contract (phase 9c).
export type Project = Schema<"ProjectRecord">;
export type ProjectDetail = Project;
export type Question = Schema<"QuestionRecord">;
export type CpfParameter = Schema<"CpfParameterRow">;

// provenance sources that count as measured / literature evidence (vs fitted or predicted)
export const MEASURED_SOURCES = ["measured", "Publication", "Database", "Other"];

/** A compound's CPF as the compound page shows it: the API's CPF view, with the project it belongs to. */
export type Compound = {
  name: string;
  project: string;
  version: number;
  completeness: number; // 0..1 (S0 readiness)
  parameters: CpfParameter[];
};

// What a round's verdict rests on (plan §9.4): judged studies, how many are real observed data, by origin.
export type RealData = {
  judged: number;
  real: number;
  byOrigin: Record<string, number>;
  notReal: string[];
  notEvaluable: string[];
  passable: boolean;
  label: string;
};

export type Round = {
  round: number;
  action: string;
  aucGmfe: number | null;
  cmaxGmfe: number | null;
  verdict: string;
  realData?: RealData;
  cycle?: number;
};

export type Stage = {
  stage: string;
  label: string;
  status: "RUNNING" | "PASSED" | "ACCEPTED" | "SKIPPED" | "ESCALATED" | "ABORTED" | "FAILED" | "PENDING";
  rounds: Round[];
  notes?: string[]; // why a stage was skipped, studies it could not simulate, what the build deferred
};

export type Campaign = {
  id: string;
  project?: string;
  status?: string; // QUEUED | RUNNING | COMPLETED | ESCALATED (from the runner)
  compound: string;
  question: string;
  modelRisk: Rating;
  budgetSeconds: number;
  elapsedSeconds: number;
  currentStage: string;
  stages: Stage[];
};

export type GofSeries = { name: string; time_h: number[]; concentration: number[]; unit: string; kind: "simulated" | "observed" };

// The campaign monitor's full read view: the campaign plus its goodness-of-fit series.
// S6: sensitivity ranking and prediction intervals per study; S7: the package record (no server paths are shown).
export type Band = { p5: number; p50: number; p95: number; n: number };
export type Prediction = {
  sensitivity?: Record<string, { parameter: string; pk_parameter: string; value: number }[]>;
  intervals?: Record<string, { AUC?: Band; Cmax?: Band }>;
  notes?: string[];
};
export type PackageRecord = {
  exportable: boolean;
  reproduction?: { passes: boolean; compared: number; failures: { path: string; status: string; detail?: string }[] };
  report?: Record<string, string>;
  data_bundle_sha256?: string;
  package_sha256?: string;
  files?: number;
  report_notes?: string[];
};
export type EngineIdentity = { kind: "pksim" | "software-fixture" | "injected" | "unknown"; command: string };
// Plan §12.3 N6: every change of the working parameter set and the study verdicts it moved.
export type LedgerEntry = {
  seq: number;
  stage: string;
  cycle?: number;
  event?: boolean;
  kind: string;
  reason: string;
  cpf_before: string;
  cpf_after: string;
  changes: { parameter: string; before: number | string | null; after: number | string | null; unit?: string | null; status?: string; fitted_at_stage?: string | null }[];
  verdicts: { study_id: string; stage: string; before: string; after: string; model_set_before?: string | null; model_set_after?: string | null }[];
  note?: string;
};
// Plan §12.3 N5: parameters × studies, structural (in the simulation) and quantitative (S6 sensitivity).
export type InfluenceMap = {
  cpf_sha256: string;
  parameters: string[];
  studies: string[];
  cells: Record<string, Record<string, { structural: boolean; auc: number | null; cmax: number | null }>>;
  quantitative: boolean;
  status?: Record<string, string>;
  fitted_at_stage?: Record<string, string | null>;
};
export type CampaignDetail = Campaign & {
  gof?: GofSeries[];
  prediction?: Prediction | null;
  package?: PackageRecord | null;
  engine?: EngineIdentity | null;
  realData?: Record<string, RealData>; // per stage, its last judged round
  ledger?: { entries: LedgerEntry[] } | null;
  influence?: InfluenceMap | null;
  cycle?: number;
  feedback?: FeedbackDecision[];
  feedbackPending?: FeedbackDiagnosis | null;
};

// Plan §12.3 N4: the diagnosis of a failed external validation (S5), and the decisions it allows.
export type FeedbackDiagnosis = {
  cycle?: number;
  failing: {
    study_id: string; class: string; group?: string | null; failed: string[]; ratio: Record<string, number>;
    direction: string; learn_stage: string; differences: string[];
    influences: { parameter: string; auc: number | null; cmax: number | null }[];
    ms01?: { path: 1 | 2 | 3; action: string; why: string };   // MS-01 §6.6 for this study
  }[];
  recommendation?: { action: string; studies: string[]; why: string } | null;  // a suggestion; the person decides
  classes: Record<string, { failing: string[]; unspent: string[]; cycles: number;
    learn: { possible: boolean; reason: string; needs_deviation?: boolean } }>;
  notAchievable: string[];
  notes?: string[];
};
export type FeedbackDecision = {
  cycle: number;
  action: "limitation" | "learn" | "new_evidence" | "stop";
  failing?: string[];
  studies?: string[];
  stages?: Record<string, string>;
  statement?: string;
  parameter?: string;
  value?: number;
  unit?: string | null;
  reference?: string;
  signature_id?: string;
  note?: string;
};

export type Escalation = {
  id: string;
  campaignId: string;
  stage: string;
  reasonCode: string;
  evidence: string;
  options: { id: string; label: string; requiresSignature: boolean; disabled?: string }[];
  feedback?: FeedbackDiagnosis;
};

export type Proposal = Schema<"ProposalRecord">;
