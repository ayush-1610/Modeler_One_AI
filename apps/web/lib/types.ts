// The shapes the read APIs return, mirroring the backend domain models. This file used to carry sample data that
// pages showed whenever a read failed; that hid real faults behind made-up numbers, so it holds types only now.

import type { Rating } from "@/lib/api";

export type Project = { id: string; name: string; compounds: string[]; openQuestions: number; risk: Rating };
export type ProjectDetail = Project & { questions?: Question[] };

export type CpfParameter = {
  id: string;
  value: string | null;
  unit: string | null;
  status: string; // CPF status: fixed | fitted | predicted | derived
  source: string; // provenance source_type (drives the provenance chip)
  reference: string;
  fittableStages: string[];
};

// provenance sources that count as measured / literature evidence (vs fitted or predicted)
export const MEASURED_SOURCES = ["measured", "Publication", "Database", "Other"];

export type Compound = {
  name: string;
  project: string;
  version: number;
  completeness: number; // 0..1 (S0 readiness)
  parameters: CpfParameter[];
};

export type Question = {
  id: string;
  question: string;
  application: string;
  modelRisk: Rating | null;
  stage: "planning" | "evaluation" | "reporting" | "signed";
  failingCriteria: number;
};

export type Round = {
  round: number;
  action: string;
  aucGmfe: number | null;
  cmaxGmfe: number | null;
  verdict: string;
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
export type CampaignDetail = Campaign & {
  gof?: GofSeries[];
  prediction?: Prediction | null;
  package?: PackageRecord | null;
  engine?: EngineIdentity | null;
};

export type Escalation = {
  id: string;
  campaignId: string;
  stage: string;
  reasonCode: string;
  evidence: string;
  options: { id: string; label: string; requiresSignature: boolean }[];
};

export type Proposal = {
  id: string;
  parameterId: string;
  value: string;
  unit: string | null;
  quote: string;
  reference: string;
  agent: string;
};
