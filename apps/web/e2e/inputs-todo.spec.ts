// T-49: what keeps P4 from ready is listed on the Model inputs page with what settles it, and settled there: one of
// two values more than 2-fold apart kept (values within 10 % are one value, D-32), a placeholder target corrected, a pKa
// called acidic or basic, the refiled value checked. Reproduces the evidence of a real project (2026-10-06); the values
// are test entries, never a model.
import { expect, type Page, test } from "@playwright/test";

import { SIDEBAR_PREFETCH, finishStart, requestsDuring } from "./fixtures/inputs";

const AUTH = { Authorization: "Bearer dev" };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

/** A decision on Compound costs the decision and the inputs read again (final review round 4; round 3 read the evidence
 *  and the other projects' offers too): the evidence is the decision's answer, written; the offers change only when a
 *  value is newly held here, and only by losing one, so they are read again then and only when one is shown (`also`).
 *  The step bar is drawn again at most once, when the readiness changed, and no link of the page is prefetched again. */
function onlyTheInputs(sent: string[], post: RegExp, also: string[] = []) {
  const said = sent.join("\n");
  expect(sent.filter((s) => s.startsWith("POST")), said).toHaveLength(1);
  expect(sent.find((s) => s.startsWith("POST")), said).toMatch(post);
  expect(sent.filter((s) => s.startsWith("GET")).sort(), said).toEqual(["GET inputs", ...also].sort());
  expect(sent.filter((s) => s.startsWith("server render")).length, said).toBeLessThanOrEqual(1);
  expect(sent.filter((s) => s.startsWith("prefetch") && !SIDEBAR_PREFETCH.test(s)), said).toEqual([]);
}

test("open P4 items are settled on the Model inputs page", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "desvenlafaxine", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nER tablet 50 mg.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);      // Inputs opens once Start is done (page review 1, decision 7)
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  const add = async (req_id: string, target: string, value: number, extra: Record<string, unknown> = {}, pksim?: number) => {
    const res = await request.post(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH, data: {
      req_id, target, value, source_type: "PUBLICATION", doi: "10.2147/DDDT.S80886", title: "Desvenlafaxine review", year: 2015,
      quote: `${target} ${value}`, ...extra } });
    expect(res.status(), await res.text()).toBe(201);
    const id = (await res.json()).data.id as string;
    const decided = await request.post(`/api/v1/projects/${projectId}/evidence/${id}:decide`, { headers: AUTH,
      data: { state: "ACCEPTED", reason: "read in the paper", ...(pksim === undefined ? {} : { value_pksim: pksim }) } });
    expect(decided.ok(), await decided.text()).toBeTruthy();
  };
  await add("REQ-bind.fu", "bind.fu", 0.70);
  await add("REQ-bind.fu", "bind.fu", 0.30);
  await add("REQ-elim.pathway", "elim", 0.45, {}, 0.45);
  await add("REQ-phys.pka", "phys.pka", 10.11);
  await add("REQ-phys.logp", "phys.logp", 2.29);
  await add("REQ-phys.logp", "phys.logp", 2.35);       // within 10 %: one value with two sources, no decision (D-32)

  await page.goto(`/projects/${projectId}/inputs`);
  const missing = page.getByTestId("still-missing");
  await expect(missing).toContainText("What needs you");
  await expect(missing.getByTestId("missing-conflict-bind.fu")).toBeVisible();
  await shot(page, "1-todo");
  await page.getByTestId("tab-compound").click();                 // each item is settled in its area

  await expect(page.getByTestId("todo-conflict-phys.logp")).toHaveCount(0);
  // two fu values more than 2-fold apart: keep one, the other is rejected with the reason
  const fu = page.getByTestId("todo-conflict-bind.fu");
  await fu.getByRole("radio").first().check();
  await fu.getByLabel("reason for bind.fu").fill("equilibrium dialysis, human plasma");
  await page.waitForLoadState("networkidle");
  const kept = await requestsDuring(page, projectId, async () => {
    await fu.getByRole("button", { name: "Keep the selected value, reject the others" }).click();
    await expect(page.getByText("Fraction unbound in plasma: one value kept")).toBeVisible();
  });
  onlyTheInputs(kept, /^POST evidence\/ev-[0-9a-f]+:choose$/);
  // another project of the drug (another spec's) may offer values: a value newly held here may take one of them away
  const offered = (await page.locator('[data-testid^="reuse-use-"]').count()) > 0;
  await expect(page.getByTestId("todo-conflict-bind.fu")).toHaveCount(0);

  // "elim" is the data plan's placeholder: file the value under the pathway; the refiled copy is held until checked
  const elim = page.getByTestId("todo-correct-elim");
  await elim.locator("select").first().selectOption("elim.renal.gfr_fraction");
  await elim.locator("input[placeholder='why']").fill("renal filtration is the main route");
  const refiled = await requestsDuring(page, projectId, async () => {
    await elim.getByRole("button", { name: "Correct" }).click();
    await expect(page.getByText(/Filed as GFR fraction \(renal filtration\)/)).toBeVisible();
  });
  onlyTheInputs(refiled, /^POST evidence\/ev-[0-9a-f]+:correct$/, offered ? ["GET value-reuse"] : []);
  const held = page.getByTestId("todo-review-elim.renal.gfr_fraction");
  await held.locator("input[placeholder='why']").fill("fraction of GFR, from the review");
  const accepted = await requestsDuring(page, projectId, async () => {
    await held.getByRole("button", { name: "Accept" }).click();
    await expect(page.getByTestId("todo-review-elim.renal.gfr_fraction")).toHaveCount(0);
  });
  onlyTheInputs(accepted, /^POST evidence\/ev-[0-9a-f]+:decide$/);

  // the pKa says neither acid nor base
  const pka = page.getByTestId("todo-pka-phys.pka");
  await pka.locator("select").selectOption("base");
  await pka.locator("input[placeholder='why']").fill("tertiary amine");
  const saved = await requestsDuring(page, projectId, async () => {
    await pka.getByRole("button", { name: "Save" }).click();
    await expect(page.getByTestId("todo-pka-phys.pka")).toHaveCount(0);
  });
  onlyTheInputs(saved, /^POST evidence\/ev-[0-9a-f]+:correct$/);               // its acid or base: no value newly held

  // what is left: values nobody has proposed yet, and data to judge the model on (opened from the side list)
  await expect(page.getByTestId("todo-missing-phys.mw")).toBeVisible();
  await page.getByTestId("tab-todo").click();
  await missing.getByTestId("missing-datasets-observed data").click();
  await expect(page.getByTestId("tab-studies")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("todo-datasets-observed data")).toBeVisible();
  await page.getByTestId("tab-compound").click();
  await expect(page.getByTestId("record-bind.fu")).toContainText("0.7");
  await expect(page.getByTestId("record-phys.pka.base.0")).toContainText("10.11");
  await expect(page.getByTestId("record-phys.logp")).toContainText("2.29");
  await shot(page, "2-settled");
});
