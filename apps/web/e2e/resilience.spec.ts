// Resilience when the API stops answering (the 2026-11-11 frontend audit, item 9): the sidebar's liveness says so even
// after an earlier good answer, a polled read that failed recovers by itself, a failed read says it in one sentence
// without upload or operator advice, a campaign id that is not recorded stops checking, and a printout holds every
// section, also those never scrolled to.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

async function project(request: import("@playwright/test").APIRequestContext, name: string): Promise<string> {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: name, extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nA resilience check.") } } });
  expect(started.ok(), await started.text()).toBeTruthy();
  return (await started.json()).data.project_id as string;
}

test("the sidebar is not live once the API stops answering, and is live again when it answers", async ({ page }) => {
  await page.goto("/");
  const conn = page.getByTestId("nav-conn");
  await expect(conn).toHaveClass(/\blive\b/);
  // the API stops answering after one good answer: asking again says so (it said 'live' from the cached answer before)
  await page.route("**/api/v1/escalations", (route) => route.fulfill({ status: 500, body: "Internal Server Error" }));
  await conn.click();
  await expect(conn).not.toHaveClass(/\blive\b/);
  await expect(conn).toHaveAttribute("title", "The API does not answer");
  // it answers again: the failed poll keeps trying (at most every 30 s) and the sidebar recovers without a reload
  await page.unroute("**/api/v1/escalations");
  await expect(conn).toHaveClass(/\blive\b/, { timeout: 45_000 });
});

test("a first read that fails keeps polling and recovers without a reload", async ({ page }) => {
  // down at page load: before, polling never started and the sidebar stayed 'not live' until a reload
  await page.route("**/api/v1/escalations", (route) => route.fulfill({ status: 500, body: "Internal Server Error" }));
  await page.goto("/");
  const conn = page.getByTestId("nav-conn");
  await expect(conn).toHaveAttribute("title", "The API does not answer");
  await page.unroute("**/api/v1/escalations");
  await expect(conn).toHaveClass(/\blive\b/, { timeout: 45_000 });
});

test("a read that fails during an outage says so in one sentence, with no upload or operator advice", async ({ page, request }) => {
  const projectId = await project(request, "Outagemide");
  await page.route("**/api/v1/projects/*/library", (route) => route.fulfill({ status: 500, body: "Internal Server Error" }));
  await page.goto(`/projects/${projectId}/library`);
  const banner = page.locator(".banner.err").filter({ hasText: "HTTP 500" });
  await expect(banner).toHaveText("The API is not answering right now (HTTP 500); what is shown may be out of date.");
  await expect(page.getByText(/fewer files|MODELER_API_BASE/)).toHaveCount(0);
});

test("a campaign id that is not recorded stops checking after half a minute and says so", async ({ page }) => {
  await page.goto("/campaigns/no-such-campaign");
  await expect(page.getByTestId("campaign-pending")).toBeVisible();
  const refreshes: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/campaigns/no-such-campaign")) refreshes.push(r.url()); });
  await expect(page.getByTestId("campaign-not-found")).toContainText("No campaign with this id is recorded.", { timeout: 45_000 });
  await expect(page.getByTestId("campaign-pending")).toHaveCount(0);
  // and it no longer refreshes the page
  const after = refreshes.length;
  await page.waitForTimeout(6_000);
  expect(refreshes.length).toBe(after);
});

test("a printout shows the sections below the fold that were never scrolled to", async ({ page, request }) => {
  const projectId = await project(request, "Printamide");
  // a short window, so the page's later sections are below the fold and wait to fade in
  await page.setViewportSize({ width: 1280, height: 420 });
  await page.goto(`/projects/${projectId}/start`);
  const pending = page.locator(".reveal-pending");
  await expect(pending.first()).toBeAttached();
  // no inline opacity: the waiting state is a class, so the print rule can override it
  expect(await pending.first().evaluate((el) => (el as HTMLElement).style.opacity)).toBe("");
  await page.emulateMedia({ media: "print" });
  expect(await pending.first().evaluate((el) => getComputedStyle(el).opacity)).toBe("1");
  await page.emulateMedia({ media: "screen" });
  // the browser's print dialog announces itself: everything waiting is shown at once
  await page.evaluate(() => window.dispatchEvent(new Event("beforeprint")));
  await expect(pending).toHaveCount(0);
});
