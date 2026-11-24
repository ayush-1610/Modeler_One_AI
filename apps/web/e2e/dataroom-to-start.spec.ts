// From the Data room to Start (plan 2026-11-24 §7, phase 4, B4 and B5), on the made-up Exampleamide's delivery (software
// test data, never client data) with no LLM provider: the delivery is read, the agents' answers are written straight into
// the store (as A6-A8 submit them), a person confirms the question card and takes the decisions, which drafts Start's
// question, applications, products, scenarios and populations on its own, each a draft to confirm ("Fill from the Data
// room" then finds nothing new); a question a person then types otherwise is kept, and Start says where it differs from
// the room (advice, never a block).
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const FIXTURE = join(__dirname, "fixtures", "dataroom.py");

function fixture(...args: string[]): Record<string, unknown> {
  const printed = execFileSync("uv", ["run", "python", FIXTURE, ...args], { cwd: REPO }).toString();
  return JSON.parse(printed.trim().split("\n").pop()!) as Record<string, unknown>;
}

test("Start is filled from the Data room's confirmed card, and a person's own question is kept and advised", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 100 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  const api = `/api/v1/projects/${projectId}/dataroom`;

  // no confirmed card yet: no button
  await page.goto(`/projects/${projectId}/start`);
  await expect(page.getByTestId("start-read")).toBeVisible();
  await expect(page.getByTestId("start-fill-from-room")).toHaveCount(0);

  const zip = fixture("zip", mkdtempSync(join(tmpdir(), "dataroom-"))).zip as string;
  const up = await request.post(`${api}/uploads`, { headers: AUTH, multipart: {
    files: { name: "Exampleamide delivery.zip", mimeType: "application/zip", buffer: readFileSync(zip) } } });
  expect(up.ok(), await up.text()).toBeTruthy();
  expect((await request.post(`${api}/run`, { headers: AUTH, data: {} })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${api}/run`, { headers: AUTH })).json()).data.state,
                    { timeout: 120_000 }).toBe("done");
  fixture("seed", join(process.env.E2E_DATA_DIR!, "read-root"), projectId);
  const room = (await (await request.get(api, { headers: AUTH })).json()).data;
  const confirmed = await request.put(`${api}/question`, { headers: AUTH, data: { card: room.question, confirmed: true, reason: "as read" } });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
  for (const d of (await confirmed.json()).data.decisions as { id: string; suggested: string }[]) {
    const made = await request.post(`${api}/decisions/${encodeURIComponent(d.id)}`, { headers: AUTH, data: { chosen: d.suggested } });
    expect(made.ok(), await made.text()).toBeTruthy();
  }

  // confirming the card and choosing the applications in the room already drafted Start (no click needed); the
  // button then finds nothing new
  await page.goto(`/projects/${projectId}/start`);
  const question = page.getByTestId("start-field-qoi.text");
  await expect(question).toContainText("reformulated Exampleamide tablet");
  await expect(question).toContainText("draft");
  await expect(page.getByTestId("start-field-qoi.applications")).toContainText("virtual bioequivalence");
  await expect(page.getByTestId("start-room-advice")).toHaveCount(0);
  await page.getByTestId("start-fill-from-room").click();
  await expect(page.getByTestId("start-notice")).toContainText("Nothing new from the Data room");

  // a person's own question: kept, and Start says where it differs from the room (advice, never a block)
  const edited = await request.put(`/api/v1/projects/${projectId}/brief`, { headers: AUTH,
    data: { changes: [{ path: "qoi.text", status: "EDITED", value: "Predict exposure of the 50 mg tablet" }] } });
  expect(edited.ok(), await edited.text()).toBeTruthy();
  await page.reload();
  await expect(page.getByTestId("start-room-advice-qoi.text")).toContainText("the Data room's confirmed question card asks");
  await page.getByTestId("start-fill-from-room").click();
  await expect(page.getByTestId("start-notice")).toContainText("1 value you or a document set was kept");
  await expect(question).toContainText("Predict exposure of the 50 mg tablet");
});
