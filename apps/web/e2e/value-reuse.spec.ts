// The same drug's values in the person's other projects (plan 2026-11-05 §3.3, build I): literature and public-source
// values only, reused here with the person's consent ("Use them"), each proposed with its source to decide as any.
// A fixture leaves the first project's literature value as the agent would (the browser flows run with no LLM).
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");

async function project(request: Parameters<typeof finishStart>[0], drug: string): Promise<string> {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: drug, extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nPBPK model.") } } });
  return (await started.json()).data.project_id as string;
}

test("another project's literature value for the same drug is reused here with its source", async ({ page, request }) => {
  const first = await project(request, "Reusamide");
  execFileSync("uv", ["run", "python", join(__dirname, "fixtures", "literature_value.py"),
                      join(process.env.E2E_DATA_DIR!, "read-root"), first], { cwd: REPO });
  const here = await project(request, "reusamide");
  await finishStart(request, here);

  await page.goto(`/projects/${here}/inputs?tab=compound`);
  const offer = page.getByTestId(`reuse-${first}`);
  await expect(offer).toContainText("1 value");
  await expect(offer).toContainText("phys.logp (Pharmacokinetics of reusamide)");
  await page.screenshot({ path: test.info().outputPath("value-reuse.png"), fullPage: true });
  // what only the client can send downloads from Inputs, beside what is still missing (moved off Start, 2026-11-06)
  const download = page.waitForEvent("download");
  await page.getByTestId("still-missing").getByTestId("request-download").click();
  expect((await download).suggestedFilename()).toMatch(/-data-request\.xlsx$/);
  await page.getByTestId(`reuse-use-${first}`).click();
  await expect(page.getByTestId("inputs-notice")).toContainText("1 value from");
  await expect(page.getByTestId("value-reuse")).toHaveCount(0);                  // nothing new left to reuse
  const evidence = (await (await request.get(`/api/v1/projects/${here}/evidence`, { headers: AUTH })).json()).data;
  const reused = evidence.evidence.find((e: { target: string }) => e.target === "phys.logp");
  expect(reused.note).toContain("reused from project");
  expect(reused.source.doi).toBe("10.1/reuse");
});
