// From a delivery to a signed MAP (plan 2026-11-24 §7, phase 4, B10), on the made-up Exampleamide's delivery (software
// test data, never client data) with no LLM provider and no engine: the delivery is read, the agents' answers written
// straight into the store (as A6-A8 submit them); a person confirms the question card and takes the decisions, and sends
// the room to the model (signed); Start holds the room's drafts, confirmed by the person; Inputs asks only for what the
// delivery does not hold (lipophilicity, an elimination pathway), entered as a modeller would; Review & sign offers the
// room's VBE design (the reformulated tablet against the reference, and the observed BE from the room's own NCA), the
// person completes and saves it, and signs the MAP. A second send of the same delivery changes nothing the MAP rests on.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const FIXTURE = join(__dirname, "fixtures", "dataroom.py");

function fixture(...args: string[]): Record<string, unknown> {
  const printed = execFileSync("uv", ["run", "python", FIXTURE, ...args], { cwd: REPO }).toString();
  return JSON.parse(printed.trim().split("\n").pop()!) as Record<string, unknown>;
}

// the canvas and the review are wide: a desktop viewport, as for a person signing
test.use({ viewport: { width: 1600, height: 1200 } });

test("a made-up delivery goes from the Data room through Start and Inputs to a signed MAP, and a second send changes nothing",
     async ({ page, request }) => {
  test.setTimeout(240_000);
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 100 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  const api = `/api/v1/projects/${projectId}`;
  const room = `${api}/dataroom`;

  // --- the Data room: read, the agents' answers, the card confirmed on the page, the decisions taken
  const zip = fixture("zip", mkdtempSync(join(tmpdir(), "dataroom-"))).zip as string;
  const up = await request.post(`${room}/uploads`, { headers: AUTH, multipart: {
    files: { name: "Exampleamide delivery.zip", mimeType: "application/zip", buffer: readFileSync(zip) } } });
  expect(up.ok(), await up.text()).toBeTruthy();
  expect((await request.post(`${room}/run`, { headers: AUTH, data: {} })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${room}/run`, { headers: AUTH })).json()).data.state,
                    { timeout: 120_000 }).toBe("done");
  fixture("seed", join(process.env.E2E_DATA_DIR!, "read-root"), projectId);
  await page.goto(`/projects/${projectId}/dataroom`);
  await expect(page.getByTestId("question-text-shown")).toContainText("reformulated Exampleamide tablet");
  await page.getByTestId("question-confirm").click();
  await expect(page.getByTestId("question-confirmed")).toBeVisible();
  const decisions = (await (await request.get(room, { headers: AUTH })).json()).data.decisions as { id: string; suggested: string }[];
  expect(decisions.map((d) => d.id)).toContain("applications");
  for (const d of decisions) {
    const made = await request.post(`${room}/decisions/${encodeURIComponent(d.id)}`, { headers: AUTH,
      data: { chosen: d.suggested, reason: "as suggested" } });
    expect(made.ok(), await made.text()).toBeTruthy();
  }

  // --- "Send to the model", on the page: nothing blocks it, and it is signed
  await page.reload();
  await page.getByTestId("rail-scenarios").click();
  await expect(page.getByTestId("publish-blocked")).toHaveCount(0);
  await expect(page.getByTestId("publish-counts")).toContainText("2 observed datasets");
  await page.getByTestId("publish-reason").fill("inputs confirmed with the client");
  await page.getByTestId("publish-send").click();
  await expect(page.getByTestId("publish").getByRole("status")).toContainText("Signed");

  // --- Start: the room's question, applications and scenarios are drafts; the person confirms them and rates M15
  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("start-field-qoi.text")).toContainText("reformulated Exampleamide tablet");
  await expect(page.getByTestId("start-field-qoi.text")).toContainText("draft");
  await expect(page.getByTestId("start-field-qoi.applications")).toContainText("virtual bioequivalence");
  const fields = (await (await request.get(`${api}/brief`, { headers: AUTH })).json()).data.brief.fields as
    Record<string, { status: string }>;
  const drafted = Object.entries(fields).filter(([, f]) => f.status === "DRAFTED").map(([path]) => path);
  expect(drafted).toEqual(expect.arrayContaining(["qoi.text", "qoi.context_of_use", "qoi.applications", "proj.agencies"]));
  const scenarios = [0, 1].flatMap((i) => ["route", "food_state", "dose"].map((k) => `scenarios[${i}].${k}`));
  const start = await request.put(`${api}/brief`, { headers: AUTH, data: { changes: [
    ...[...drafted, ...scenarios].map((path) => ({ path, status: "CONFIRMED" })),
    ...([["m15.influence_rating", "low"], ["m15.consequence_rating", "medium"], ["acceptance.tier", "medium"],
         ["drug.modality", "small_molecule"], ["scope.pbpk_model", "full"], ["scope.site_of_action", "systemic"]] as const)
      .map(([path, value]) => ({ path, status: "EDITED", value })),
  ] } });
  expect(start.ok(), await start.text()).toBeTruthy();
  expect((await start.json()).data.start.problems).toEqual([]);

  // --- Inputs: only what the delivery does not hold is asked for; a modeller enters it (made-up literature values)
  await page.goto(`/projects/${projectId}/inputs`);
  const missing = page.getByRole("region", { name: /Fill in what's missing/ });
  await expect(missing.getByRole("heading")).toContainText("(2)");                      // the molar mass etc. are the delivery's
  await expect(missing.getByRole("rowheader", { name: "Lipophilicity" })).toBeVisible();
  await expect(missing.getByRole("rowheader", { name: /An elimination pathway/ })).toBeVisible();
  expect((await request.post(`${api}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  for (const [req_id, target, value, unit, conditions] of [
    ["REQ-phys.logp", "phys.logp", 2.1, null, { type: "logP", pH: "7.4", method: "shake flask, measured" }],
    ["REQ-elim.pathway", "elim.hepatic.total.plasma_clearance", 4.2, "ml/min/kg", {}],
  ] as const) {
    const r = await request.post(`${api}/evidence`, { headers: AUTH, data: { req_id, target, value, unit, conditions,
      source_type: "PUBLICATION", doi: "10.1/made-up", year: 2020 } });
    expect(r.ok(), await r.text()).toBeTruthy();
    const id = (await r.json()).data.id as string;
    expect((await request.post(`${api}/evidence/${id}:decide`, { headers: AUTH,
      data: { state: "ACCEPTED", reason: "checked" } })).ok()).toBeTruthy();
  }
  const assembled = await request.post(`${api}/inputs:assemble`, { headers: AUTH });
  expect((await assembled.json()).data.readiness.content.ready).toBeTruthy();

  // --- Review & sign: the room's VBE design offered (the reformulated tablet the question asks about), taken, completed
  await page.goto(`/projects/${projectId}/plan?tab=applications`);
  const vbe = page.getByTestId("vbe-panel");
  await expect(vbe.getByTestId("vbe-suggested-test")).toContainText("Exampleamide_100_mg_reformulated");
  await expect(vbe.getByTestId("vbe-suggested-reference")).toContainText("Refamide_100_mg");
  await expect(vbe.getByTestId("vbe-suggested-be")).toContainText("the room's own NCA");
  await vbe.getByTestId("vbe-use-suggested").click();
  await expect(vbe.getByTestId("vbe-test_formulation")).toHaveValue("Exampleamide_100_mg_reformulated");
  await expect(vbe.getByTestId("vbe-reference_formulation")).toHaveValue("Refamide_100_mg");
  await expect(vbe.getByTestId("vbe-be-AUC_inf-gmr")).not.toHaveValue("");
  // what is never defaulted stays the person's: the variability (a harvested PK-Sim path), the trial size, seed, threshold
  await vbe.getByTestId("vbe-variability-add").click();
  await vbe.getByLabel("parameter 1").fill("Organism|Lumen|Stomach|Gastric emptying time");
  await vbe.getByLabel("CV 1").fill("30");
  await vbe.getByLabel("source 1").fill("made-up crossover study");
  await vbe.getByTestId("vbe-n_subjects").fill("24");
  await vbe.getByTestId("vbe-n_trials").fill("100");
  await vbe.getByTestId("vbe-seed").fill("20261124");
  await vbe.getByTestId("vbe-pos_threshold").fill("0.8");
  await vbe.getByTestId("vbe-reason").fill("the VBE design for the reformulated tablet");
  await vbe.getByTestId("vbe-save").click();
  await expect(page.getByTestId("vbe-problems")).toHaveCount(0);

  // the room's decisions are limitations the signer reads
  await page.getByTestId("review-tab-credibility").click();
  await expect(page.getByTestId("limitations")).toContainText("Data room decision, Applications of the question");
  await page.getByTestId("review-tab-validator").click();
  for (let i = 0; i < 6 && !(await page.getByTestId("validator-green").isVisible()); i++) {
    const warning = page.locator("[data-testid^='violation-']").first();
    const id = (await warning.getAttribute("data-testid"))!;
    await warning.getByPlaceholder("accept it because…").fill("an accepted limitation of this test project");
    await warning.getByRole("button", { name: "Acknowledge" }).click();
    await expect(page.getByTestId(id)).toHaveCount(0);
  }
  await expect(page.getByTestId("validator-green")).toBeVisible();
  await page.getByTestId("approve-and-sign").click();
  await expect(page.getByTestId("map-signed")).toContainText("MAP v1 signed");

  // --- the MAP: the room's question, the VBE design as saved, the room's decisions among its limitations
  const plan = (await (await request.get(`${api}/plan`, { headers: AUTH })).json()).data;
  expect(plan.signed).toBe(true);
  const map = JSON.parse(readFileSync(fileURLToPath(plan.map.campaign.map_uri as string), "utf-8"));
  expect(map.status).toBe("SIGNED");
  expect(map.objective).toBe("Does the reformulated Exampleamide tablet perform like the reference product in vivo?");
  const [design] = map.applications as { template: string; inputs: Record<string, unknown> }[];
  expect(design.template).toBe("vbe-crossover");
  expect(design.inputs).toMatchObject({ test_formulation: "Exampleamide_100_mg_reformulated",
    reference_formulation: "Refamide_100_mg", n_subjects: 24, n_trials: 100, seed: 20261124, pos_threshold: 0.8 });
  expect((design.inputs.observed_be as { source: string }).source).toContain("the room's own NCA");
  expect((map.split_limitations as string[]).some((l) => l.startsWith("Data room decision, Population for EX-01"))).toBe(true);

  // --- a second send of the same delivery: nothing new, the MAP stays signed, and there is nothing to sign again
  const again = await request.post(`${room}/publish`, { headers: AUTH, data: { reason: "sent again by mistake" } });
  expect(again.ok(), await again.text()).toBeTruthy();
  expect((await again.json()).data).toMatchObject({ evidence: 0, datasets: 0, superseded: 0 });
  const after = (await (await request.get(`${api}/plan`, { headers: AUTH })).json()).data;
  expect(after.signed).toBe(true);
  expect(after.map.map_sha256).toBe(plan.map.map_sha256);
  const twice = await request.post(`${api}/plan:sign`, { headers: AUTH, data: {} });
  expect(twice.status()).toBe(409);
  expect(await twice.text()).toContain("has not changed since");
  const steps = (await (await request.get(`${api}/steps`, { headers: AUTH })).json()).data.steps as
    { step: string; state: string; reasons: string[] }[];
  expect(steps.find((s) => s.step === "review")?.state).toBe("done");
  expect(steps.find((s) => s.step === "run")?.reasons).toEqual(["The MAP is signed: start the campaign from Review & sign"]);
});
