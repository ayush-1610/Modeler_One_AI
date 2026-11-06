// T-22: the compound's values from the free structured sources, read by code at the project's start (build B, plan
// 2026-11-05 §3.3; the owner, 2026-11-05: "basic compound details should take seconds"). The browser flows have no
// network to PubChem, openFDA or ChEMBL: the sources job runs on the recorded answers for an invented compound
// (software test data, never a real drug's values).
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const AUTH = { Authorization: "Bearer dev" };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("the compound's basic values are there from the start, each with its source", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 10 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "compound_sources.py"),
                      join(process.env.E2E_DATA_DIR!, "read-root"), projectId], { cwd: REPO });

  await page.goto(`/projects/${projectId}/inputs?tab=compound`);
  const read = page.getByTestId("sources-read");
  await expect(read.getByTestId("source-PubChem")).toContainText("5 values");
  await expect(read.getByTestId("source-FDA label")).toContainText("EXAMPLIX (NDA000001)");
  await expect(read.getByTestId("source-ChEMBL")).toContainText("2 values");
  await expect(read).toContainText("without saying acid or base");          // what code left for the agent and the person
  // the molecular weight is an input now, no click (it was "Missing for S0 · Molecular weight")
  await expect(page.getByTestId("missing-missing-phys.mw")).toHaveCount(0);
  await expect(page.getByTestId("still-missing")).not.toContainText("Molecular weight");
  await shot(page, "1-compound-from-the-sources");
});
