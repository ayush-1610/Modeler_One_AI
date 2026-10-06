// T-49: what keeps P4 from ready is listed on the Model inputs page with what settles it, and settled there: one of
// several accepted values kept, a placeholder target corrected, a pKa called acidic or basic, the corrected value
// accepted. Reproduces the evidence of a real project (2026-10-06); the values are test entries, never a model.
import { expect, type Page, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

test("open P4 items are settled on the Model inputs page", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "desvenlafaxine", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nER tablet 50 mg.") } },
  });
  const projectId = (await started.json()).data.project_id as string;
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
  await add("REQ-bind.fu", "bind.fu", 0.73);
  await add("REQ-elim.pathway", "elim", 0.45, {}, 0.45);
  await add("REQ-phys.pka", "phys.pka", 10.11);
  await add("REQ-phys.logp", "phys.logp", 2.29);

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("assemble").click();
  const todo = page.getByTestId("inputs-todo");
  await expect(todo).toContainText("What stops readiness");
  await shot(page, "1-todo");

  // two fu values: keep one, the other is rejected with the reason
  const fu = page.getByTestId("todo-conflict-bind.fu");
  await fu.getByRole("radio").first().check();
  await fu.getByLabel("reason for bind.fu").fill("equilibrium dialysis, human plasma");
  await fu.getByRole("button", { name: "Keep the selected value, reject the others" }).click();
  await expect(page.getByText("bind.fu: one value kept")).toBeVisible();
  await expect(page.getByTestId("todo-conflict-bind.fu")).toHaveCount(0);

  // "elim" is the data plan's placeholder: file the value under the pathway, then accept the copy
  const elim = page.getByTestId("todo-correct-elim");
  await elim.locator("select").first().selectOption("elim.renal.gfr_fraction");
  await elim.locator("input[placeholder='why']").fill("renal filtration is the main route");
  await elim.getByRole("button", { name: "Correct" }).click();
  await expect(page.getByText(/Filed as elim.renal.gfr_fraction/)).toBeVisible();
  const waiting = page.getByTestId("todo-missing-elim");
  await waiting.locator("input[placeholder='why']").fill("fraction of GFR, from the review");
  await waiting.getByRole("button", { name: "Accept" }).click();
  await expect(page.getByTestId("todo-missing-elim")).toHaveCount(0);

  // the pKa says neither acid nor base
  const pka = page.getByTestId("todo-pka-phys.pka");
  await pka.locator("select").selectOption("base");
  await pka.locator("input[placeholder='why']").fill("tertiary amine");
  await pka.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("todo-pka-phys.pka")).toHaveCount(0);

  // what is left: values nobody has proposed yet, and data to judge the model on
  await expect(page.getByTestId("todo-missing-phys.mw")).toBeVisible();
  await expect(page.getByTestId("todo-datasets-observed data")).toBeVisible();
  await page.getByRole("button", { name: "Compound" }).click();
  await expect(page.getByTestId("record-bind.fu")).toContainText("0.7");
  await expect(page.getByTestId("record-phys.pka.base.0")).toContainText("10.11");
  await shot(page, "2-settled");
});
