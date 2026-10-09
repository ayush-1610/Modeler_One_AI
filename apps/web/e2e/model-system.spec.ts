// Multi-compound phase 3 (MS-01 v1.3 §6.5): a project's model system on its page (compounds, roles, formation, the
// dose fraction of every product, where each analyte is judged) and the analyte and product chosen per uploaded study.
// Two minimal compounds seeded through the API: software test data, never a model.
import { expect, test } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

test("a model system is shown, its dose fractions are edited, and a study names its analyte", async ({ page, request }) => {
  const name = `Systemamide ${Date.now()}`;
  const created = await request.post("/api/v1/projects", {
    headers: AUTH, data: { name, compound: "Parentamide", question: "Exposure of the parent and its metabolite" },
  });
  expect(created.ok()).toBeTruthy();
  const projectId = (await created.json()).data.id as string;
  for (const compound of ["Parentamide", "Metabolamide"]) {
    const put = await request.put(`/api/v1/projects/${projectId}/compounds/${compound}/cpf`, { headers: AUTH, data: { compound } });
    expect(put.ok()).toBeTruthy();
  }
  const plasma = (c: string) => `Organism|PeripheralVenousBlood|${c}|Plasma (Peripheral Venous Blood)`;
  const links = {
    name: "Parentamide", compounds: ["Parentamide", "Metabolamide"],
    roles: { Parentamide: "parent", Metabolamide: "metabolite" },
    products: { "Parentamide HCl 10 mg": { Parentamide: 0.9 } },
    analytes: {
      Parentamide: { name: "Parentamide", kind: "compound", compound: "Parentamide", output_path: plasma("Parentamide") },
      Metabolamide: { name: "Metabolamide", kind: "compound", compound: "Metabolamide", output_path: plasma("Metabolamide") },
    },
  };
  expect((await request.put(`/api/v1/projects/${projectId}/system`, { headers: AUTH, data: links })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}`);
  const panel = page.getByTestId("system-panel");
  await expect(panel.getByTestId("system-compound-Metabolamide")).toContainText("metabolite");
  await expect(panel.getByTestId("system-analyte-Parentamide")).toContainText("S1 · S2 · S3 · SJ · S4 · S5");
  await expect(panel.getByTestId("system-analyte-Metabolamide")).toContainText("SM · SJ · S4 · S5");

  // a dose fraction is required and never defaulted: an empty one is refused, a real one is saved
  const fraction = panel.getByLabel("Dose fraction of Parentamide in Parentamide HCl 10 mg");
  await fraction.fill("");
  await panel.getByRole("button", { name: "Save dose fractions" }).click();
  await expect(panel.getByTestId("system-outcome")).toContainText("never defaulted");
  await fraction.fill("0.912");
  await panel.getByRole("button", { name: "Save dose fractions" }).click();
  await expect(panel.getByTestId("system-outcome")).toContainText("Dose fractions saved");
  const stored = await request.get(`/api/v1/projects/${projectId}/system`, { headers: AUTH });
  expect((await stored.json()).data.system.products["Parentamide HCl 10 mg"].Parentamide).toBe(0.912);

  // the upload names what the study measures and the product it gives, from the system
  await page.goto(`/projects/${projectId}/intake`);
  await page.getByRole("button", { name: "Use example data" }).click();
  await expect(page.getByTestId("intake-analyte")).toContainText("Metabolamide (judged at SM, SJ, S4, S5)");
  await expect(page.getByTestId("intake-product")).toContainText("Parentamide HCl 10 mg");
});
