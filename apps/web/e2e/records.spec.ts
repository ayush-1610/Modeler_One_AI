// A project's records in the console (the redesign's slice 7): History in four tabs whose choice is in the address
// (the audit trail with its filter, the signatures given on the project's records (R-N09), every artifact's versions,
// what is out of date), the chain's state in the header; and Agent activity (R-N05): each agent run on the project,
// opened on its steps. The agent run is seeded in the API's read root: software test data, no model called.
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const PROPOSAL = "# Proposal\nPBPK model of Recordamide. Oral tablet, 50 mg, in healthy adults.";

function seedRun(projectId: string, runId: string) {
  const folder = join(process.env.E2E_DATA_DIR!, "read-root", "dev", "agent_runs", runId);
  mkdirSync(folder, { recursive: true });
  writeFileSync(join(folder, "run.json"), JSON.stringify({
    run_id: runId, tenant_id: "dev", project_id: projectId, agent: "A2-literature", started_by: "dev-user",
    provider: "nvidia", model: "nemotron", campaign_id: null, budget: { max_turns: 4 }, status: "COMPLETED",
    started_at: "2026-11-24T10:00:00+00:00", finished_at: "2026-11-24T10:03:20+00:00",
    input_tokens: 12400, output_tokens: 980, cost_usd: 0, summary: {}, proposals: [],
  }));
  const steps = [
    { type: "model_switch", turn: 1, from: "ollama/qwen", to: "nvidia/nemotron", why: "it is resting after a recent failure" },
    { type: "model_turn", turn: 1, model: "nemotron", content: "", tool_calls: [{ id: "c1", name: "search_europe_pmc", arguments: {} }] },
    { type: "tool_call_rejected", turn: 2, error: "fetch_page: the address is not one the search returned" },
    { type: "model_turn", turn: 2, model: "nemotron", content: "Nothing more to propose.", tool_calls: [] },
  ];
  writeFileSync(join(folder, "steps.jsonl"), steps.map((s, i) => JSON.stringify({
    seq: i + 1, kind: s.type, at: `2026-11-24T10:0${i}:00+00:00`, content: s, usage: {} })).join("\n") + "\n");
}

test("History in tabs with the signature register, and Agent activity with a run's steps", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Recordamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from(PROPOSAL) } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  // a signature on one of the project's records, through the API (the DEV sign-in carries a fresh step-up)
  const signed = await request.post(`/api/v1/projects/${projectId}/signatures`, { headers: AUTH, data: {
    meaning: "Reviewed", record_type: "test-record", record_id: `${projectId}/records-e2e`, record_sha256: "a".repeat(64) } });
  expect(signed.ok(), await signed.text()).toBeTruthy();
  const signatureId = (await signed.json()).signature_id as string;
  seedRun(projectId, "ar_recordse2e01");

  // History: the audit trail by default, the chain's state in the header, a filter over the events
  await page.goto(`/projects/${projectId}/history`);
  await expect(page.getByTestId("history-chain")).toHaveText("hash chain verifies");
  await expect(page.getByTestId("history-tab-audit")).toHaveAttribute("aria-current", "page");
  const audit = page.getByTestId("audit-table");
  await expect(audit).toContainText("signature.create");
  await page.getByTestId("audit-filter").fill("signature.create");
  await expect(audit.locator("tbody tr")).toHaveCount(1);

  // the signatures given on the project's records
  await page.getByTestId("history-tab-signatures").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/history\\?tab=signatures$`));
  const signature = page.getByTestId(`signature-${signatureId}`);
  await expect(signature).toContainText("Reviewed");
  await expect(signature).toContainText(`${projectId}/records-e2e`);
  await expect(signature).toContainText("aaaaaaaaaaaa…");

  // every artifact's versions, one opened on its changes; and what is out of date
  await page.getByTestId("history-tab-versions").click();
  await page.getByRole("link", { name: "brief/main" }).click();
  await expect(page.getByTestId("history-versions")).toContainText("v1");
  await expect(page.getByTestId("history-tab-versions")).toHaveAttribute("aria-current", "page");
  await page.getByTestId("history-tab-stale").click();
  await expect(page.getByTestId("history-stale")).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("history.png"), fullPage: true });

  // Agent activity, from the side navigation: the seeded run, its fallback and its refused call
  await page.getByTestId("nav-agent-activity").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/agent-activity$`));
  const row = page.getByTestId("agent-run-ar_recordse2e01");
  await expect(row).toContainText("A2 · searches the literature");
  await expect(row).toContainText("nemotron");
  await expect(row.getByTestId("agent-run-fallback-ar_recordse2e01")).toHaveText("after ollama/qwen");
  await expect(row).toContainText("3 min 20 s");
  await expect(row).toContainText("12k / 980");
  await page.screenshot({ path: test.info().outputPath("agent-activity.png"), fullPage: true });
  await row.getByRole("link", { name: "A2 · searches the literature" }).click();
  await expect(page.getByTestId("agent-run-facts")).toContainText("nvidia / nemotron");
  const steps = page.getByTestId("run-steps");
  await expect(steps.getByTestId("run-step-1")).toContainText("ollama/qwen → nvidia/nemotron");
  await expect(steps.getByTestId("run-step-2")).toContainText("calls search_europe_pmc");
  await expect(steps.getByTestId("run-step-3")).toContainText("a tool call refused");
  await expect(steps.getByTestId("run-step-4")).toContainText("Nothing more to propose.");
});
