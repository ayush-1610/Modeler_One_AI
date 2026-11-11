// The compound's CPF page (the 2026-11-11 audit 2, item 3): the published Dapagliflozin model's CPF, loaded through the
// API from its starting point (the OSP reference snapshot, real published data), stays a readable table. Its expression
// profiles are thousands of characters of JSON each; printed in a 16ch cell they made the page 79,498 px tall at 1280
// and split numbers mid-digit. A number is now one line at its stored precision, a structured value one summary line
// with the verbatim text behind it, and the page stays short.
import { expect, test, type APIRequestContext } from "@playwright/test";

const AUTH = { Authorization: "Bearer dev" };

async function dapagliflozin(request: APIRequestContext) {
  const template = (await (await request.get("/api/v1/templates/dapagliflozin-osp", { headers: AUTH })).json()).data;
  const created = await request.post("/api/v1/projects", { headers: AUTH, data: {
    name: `${template.compound} CPF ${Date.now()}`, compound: template.compound, question: template.question,
    model_risk: template.model_risk, exploratory: false } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const projectId = (await created.json()).data.id as string;
  const cpf = await request.put(`/api/v1/projects/${projectId}/compounds/${template.compound}/cpf`, { headers: AUTH,
    data: { ...template.cpf, compound: template.compound } });
  expect(cpf.ok(), await cpf.text()).toBeTruthy();
  const stored = (await (await request.get(`/api/v1/projects/${projectId}/compounds/${template.compound}/cpf`,
    { headers: AUTH })).json()).data;
  return { url: `/projects/${projectId}/compounds/${encodeURIComponent(template.compound)}`,
           parameters: stored.parameters as { id: string; value: number | string | null }[] };
}

test("the CPF page summarises structured values, keeps every number whole and stays short", async ({ page, request }) => {
  const { url, parameters } = await dapagliflozin(request);
  const structured = parameters.filter((p) => typeof p.value === "string" && /^\s*[[{]/.test(p.value));
  expect(structured.length, "the published model carries its expression profiles").toBeGreaterThan(0);

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto(url);
  const table = page.getByTestId("cpf-parameters");
  await expect(table.locator("tbody tr").first()).toBeVisible();
  // every row, when there are more than 50 (the guard is on the whole table, not its first page)
  const all = page.getByTestId("cpf-parameters-more-all");
  if (await all.count()) await all.click();
  await expect(table.locator("tbody tr")).toHaveCount(parameters.length);

  // the page height guard: about 3k px for the whole table, far from the 79,498 px it was
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  expect(height).toBeLessThan(15_000);

  // each structured value is one summary line; the stored text is behind it, verbatim and unchanged
  const clips = table.getByTestId("cpf-structured");
  await expect(clips).toHaveCount(structured.length);
  const first = clips.first();
  await expect(first.locator("summary")).toContainText("structured value");
  const full = await first.locator(".clip-full").textContent();
  expect(structured.map((p) => p.value)).toContain(full);
  // the summary is not the start of the text, so it gives the whole length, never "+ N characters" (audit 2 review)
  await expect(first.locator(".clip-more")).toHaveText(`show the full text (${full!.length.toLocaleString("en-US")} characters)`);

  // a number is never split: every numeric value cell is one line and shows the stored value as stored
  const numbers = table.locator(".cpf-number");
  expect(await numbers.count()).toBeGreaterThan(0);
  const lines = await numbers.evaluateAll((els) => els.map((el) => {
    const style = getComputedStyle(el);
    return { text: el.textContent ?? "", oneLine: el.getBoundingClientRect().height <= parseFloat(style.lineHeight) * 1.5,
             nowrap: style.whiteSpace === "nowrap" };
  }));
  for (const l of lines) expect(l, l.text).toMatchObject({ oneLine: true, nowrap: true });
  const stored = new Set(parameters.map((p) => String(p.value)));
  for (const l of lines) expect(stored.has(l.text), `${l.text} is the stored value`).toBeTruthy();

  // a provenance tag is one line
  const tags = await table.locator(".prov").evaluateAll((els) => els.map((el) => getComputedStyle(el).whiteSpace));
  expect(new Set(tags)).toEqual(new Set(["nowrap"]));

  // on a phone the table scrolls inside its own box; the page itself does not scroll sideways
  await page.setViewportSize({ width: 390, height: 844 });
  const wide = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(wide).toBeLessThanOrEqual(390);
});
