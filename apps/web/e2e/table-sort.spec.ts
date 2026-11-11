// The 2026-11-11 audit, item 11: a long table sorts by its heads, filters by text and shows its rows a page at a time;
// the default order is the order the rows arrive in. Checked on the published Dapagliflozin model's 40 studies (a
// software check of the table: no PK-Sim run here, and no number in it is a simulation result).
import { expect, test, type Page } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const AUTH = { Authorization: "Bearer dev" };

const studyIds = (page: Page) =>
  page.locator("table.studies-table tbody tr").evaluateAll((rows) => rows.map((r) => r.getAttribute("data-testid")));

test("the studies table pages, sorts by its heads and filters, in the API's order by default", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: AUTH,
    multipart: { drug_name: "Dapagliflozin", extract: "false",
                 files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral 10 mg, healthy adults.") } },
  });
  expect(started.ok(), await started.text()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs`);
  await page.getByTestId("published-model-dapagliflozin-osp").click();
  await expect(page.getByTestId("inputs-notice")).toContainText("40 datasets added");
  await page.getByTestId("tab-studies").click();

  const api = await request.get(`/api/v1/projects/${projectId}/inputs`, { headers: AUTH });
  const all = ((await api.json()).data.studies as { study_id: string; blinded: boolean; regimen_missing: boolean }[]);
  expect(all.length).toBe(40);
  const pinned = all.filter((s) => s.blinded || s.regimen_missing).map((s) => s.study_id);

  // the first page: the first 20 in the API's order, with every study that needs attention pinned in its place
  const expected = all.filter((s, i) => i < 20 || pinned.includes(s.study_id)).map((s) => `study-${s.study_id}`);
  await expect.poll(() => studyIds(page)).toEqual(expected);
  const more = page.getByTestId("studies-more");
  await expect(more).toContainText(`${expected.length} of 40 studies`);
  if (pinned.length) await expect(more).toContainText(`${pinned.length} need`);

  // "Show N more" shows the rest, in place
  await page.getByTestId("studies-more-next").click();
  await expect.poll(() => studyIds(page)).toEqual(all.map((s) => `study-${s.study_id}`));
  await expect(page.getByTestId("studies-more-next")).toHaveCount(0);
  await expect(more).toBeFocused();                                         // focus went to the count line, which stays

  // the Study head: ascending, then descending (from the keyboard), then back to the API's order
  const head = page.locator("table.studies-table th", { hasText: "Study" });
  await expect(head).toHaveAttribute("aria-sort", "none");
  await head.getByRole("button").click();
  await expect(head).toHaveAttribute("aria-sort", "ascending");
  const ids = all.map((s) => s.study_id);
  const asc = [...ids].sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }));
  await expect.poll(() => studyIds(page)).toEqual(asc.map((id) => `study-${id}`));
  await head.getByRole("button").focus();
  await page.keyboard.press("Enter");
  await expect(head).toHaveAttribute("aria-sort", "descending");
  await expect.poll(async () => (await studyIds(page))[0]).toBe(`study-${asc[asc.length - 1]}`);
  await head.getByRole("button").click();
  await expect(head).toHaveAttribute("aria-sort", "none");
  await expect.poll(() => studyIds(page)).toEqual(ids.map((id) => `study-${id}`));

  // the filter narrows the rows (a study that needs attention stays)
  const target = ids.find((id) => !pinned.includes(id)) ?? ids[0];
  await page.getByTestId("studies-filter").fill(target);
  await expect(page.getByTestId(`study-${target}`)).toBeVisible();
  const narrowed = ids.filter((id) => id.toLowerCase().includes(target.toLowerCase()) || pinned.includes(id));
  await expect.poll(async () => (await studyIds(page)).length).toBeLessThanOrEqual(narrowed.length);
  for (const id of pinned) await expect(page.getByTestId(`study-${id}`)).toBeVisible();
});
