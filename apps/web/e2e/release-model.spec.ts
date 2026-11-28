// A formulation's release model chosen on Inputs (the owner's D1; plan 2026-11-26 §8), on the made-up Exampleamide
// delivery (software test data, never client data): the Data room sends its reformulated tablet (the profile levels off
// at 87 %) with the Weibull fit and the room's suggestion as a proposal; on Formulations a person holds it for particle
// dissolution with a reason, then enters its particle radius and unstirred-layer thickness as the source states them
// (parameter registry 1.3: converted to µm and mm), and the formulation is built as particle dissolution.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { expect, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

const REPO = resolve(__dirname, "../../..");
const FIXTURE = join(__dirname, "fixtures", "dataroom.py");
const NAME = "Exampleamide_100_mg_reformulated";

function fixture(...args: string[]): Record<string, unknown> {
  const printed = execFileSync("uv", ["run", "python", FIXTURE, ...args], { cwd: REPO }).toString();
  return JSON.parse(printed.trim().split("\n").pop()!) as Record<string, unknown>;
}

test("a formulation held for particle dissolution on Inputs gets its particle inputs and is built so", async ({ page, request }) => {
  test.setTimeout(180_000);
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 100 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  const api = `/api/v1/projects/${projectId}`;
  const room = `${api}/dataroom`;

  // the room read, the agents' answers seeded, the question confirmed, every room decision taken as suggested, sent
  const zip = fixture("zip", mkdtempSync(join(tmpdir(), "dataroom-"))).zip as string;
  expect((await request.post(`${room}/uploads`, { headers: AUTH, multipart: {
    files: { name: "Exampleamide delivery.zip", mimeType: "application/zip", buffer: readFileSync(zip) } } })).ok()).toBeTruthy();
  expect((await request.post(`${room}/run`, { headers: AUTH, data: {} })).ok()).toBeTruthy();
  await expect.poll(async () => (await (await request.get(`${room}/run`, { headers: AUTH })).json()).data.state,
                    { timeout: 120_000 }).toBe("done");
  fixture("seed", join(process.env.E2E_DATA_DIR!, "read-root"), projectId);
  const view = (await (await request.get(room, { headers: AUTH })).json()).data;
  const confirmed = await request.put(`${room}/question`, { headers: AUTH, data: { card: view.question, confirmed: true } });
  expect(confirmed.ok(), await confirmed.text()).toBeTruthy();
  for (const d of (view.decisions as { id: string; suggested: string; on_inputs: boolean }[]).filter((x) => !x.on_inputs)) {
    expect((await request.post(`${room}/decisions/${encodeURIComponent(d.id)}`, { headers: AUTH,
      data: { chosen: d.suggested, reason: "as suggested" } })).ok()).toBeTruthy();
  }
  // Start is finished first: the send to the model waits for it (the owner's D4; plan 2026-11-27-one-way-in step 5)
  const fields = (await (await request.get(`/api/v1/projects/${projectId}/brief`, { headers: AUTH })).json()).data.brief
    .fields as Record<string, { status: string }>;
  const scenarios = [0, 1].flatMap((i) => ["route", "food_state", "dose"].map((k) => `scenarios[${i}].${k}`));
  const drafted = [...Object.entries(fields).filter(([, f]) => f.status === "DRAFTED").map(([path]) => path), ...scenarios]
    .map((path) => ({ path, status: "CONFIRMED" }));
  const confirmedStart = await request.put(`/api/v1/projects/${projectId}/brief`, { headers: AUTH, data: { changes: drafted } });
  expect(confirmedStart.ok(), await confirmedStart.text()).toBeTruthy();
  await finishStart(request, projectId);
  const sent = await request.post(`${room}/publish`, { headers: AUTH, data: { reason: "sent for the release model" } });
  expect(sent.ok(), await sent.text()).toBeTruthy();

  // Formulations: the room's proposal, held for particle dissolution with a reason
  await page.goto(`/projects/${projectId}/inputs?tab=formulations`);
  const card = page.getByTestId("release-models").getByTestId(`proposal-${NAME}`);
  await expect(card).toHaveAttribute("data-state", "proposed");
  await expect(card).toContainText("the highest mean is 87 %");
  await card.getByTestId(`release-hold-open-${NAME}`).click();
  await expect(card.getByTestId(`release-hold-${NAME}-confirm`)).toBeDisabled();       // a hold needs its reason
  await card.getByTestId(`release-hold-reason-${NAME}`).fill("the plateau is the solubility limit in the medium");
  await card.getByTestId(`release-hold-${NAME}-confirm`).click();
  await expect(card).toHaveAttribute("data-state", "held");
  await expect(card).toContainText("the plateau is the solubility limit in the medium");

  // its particle inputs, as the source states them: converted to the builder's µm and mm
  await expect(card.getByTestId(`particles-enter-${NAME}`)).toBeDisabled();
  await card.getByTestId(`particles-radius-${NAME}`).fill("0.05");
  await card.getByLabel(`unit of the particle radius for ${NAME}`).fill("mm");
  await card.getByTestId(`particles-thickness-${NAME}`).fill("30");
  await card.getByLabel(`unit of the layer thickness for ${NAME}`).fill("µm");
  await card.getByTestId(`particles-title-${NAME}`).fill("Particle size report (made up)");
  await page.screenshot({ path: test.info().outputPath("release-model-particles.png"), fullPage: true });
  await card.getByTestId(`particles-enter-${NAME}`).click();
  await expect(page.getByTestId("release-models")).toHaveCount(0);

  const evidence = (await (await request.get(`${api}/evidence`, { headers: AUTH })).json()).data.evidence as
    { target: string; state: string; value: unknown; value_pksim: number | null }[];
  const kept = Object.fromEntries(evidence.filter((e) => e.target.startsWith(`form.${NAME}.`) && e.state === "ACCEPTED")
    .map((e) => [e.target.slice(`form.${NAME}.`.length), e]));
  expect(kept.type.value).toBe("Particles");
  expect(kept["particles.radius"].value_pksim).toBe(50);
  expect(kept["particles.thickness"].value_pksim).toBeCloseTo(0.03, 6);
  expect(Object.keys(kept).filter((k) => k.startsWith("weibull."))).toEqual([]);          // the Weibull values set aside
});
