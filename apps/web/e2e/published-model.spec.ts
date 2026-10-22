// R5: the published OSP model of the drug is a source on the Inputs step (in place of the Quick start wizard). Its values
// and its clinical datasets flow in citing the model and their publications, ranked below the client and the
// literature; nothing is accepted. Software check of the pipeline: no PK-Sim run here.
import { expect, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

test("the published Dapagliflozin model's values and studies are taken as a source on Inputs", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Dapagliflozin", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg, healthy adults.") } },
  });
  expect(started.ok(), await started.text()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("published-model-dapagliflozin-osp").click();
  await expect(page.getByTestId("inputs-notice")).toContainText("The published OSP Dapagliflozin model: 42 values and 40 datasets added");
  // the model's fitted UGT1A9 clearance is on the row, cited to the model: not a made-up value
  await expect(page.getByTestId("record-elim.hepatic.UGT1A9.clspec")).toBeVisible();
  await page.getByTestId("tab-studies").click();
  await expect(page.getByTestId("study-boulton-2013-14c-dapagliflozin-iv")).toBeVisible();
  await expect(page.locator(".evidence", { hasText: "boulton-2013-14c-dapagliflozin-iv" })).toContainText("osp library");
  await page.screenshot({ path: test.info().outputPath("published-model.png"), fullPage: true });

  // taken twice, it adds nothing
  await page.getByTestId("published-model-dapagliflozin-osp").click();
  await expect(page.getByTestId("inputs-notice")).toContainText("0 values and 0 datasets added, 82 already here");
});
