// The frame around every page: a keyboard reaches the page past the sidebar in one step, the sidebar says where you
// are, and an address with no page says so instead of Next's default screen.
import { expect, test } from "@playwright/test";

test("the skip link, the current page in the sidebar, and an address with no page", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to the page" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeInViewport();
  await page.keyboard.press("Enter");
  await expect(page.locator("#content")).toBeFocused();
  await page.keyboard.press("Tab");
  // the next stop is on the page, not in the sidebar
  expect(await page.evaluate(() => !!document.activeElement?.closest(".content"))).toBe(true);

  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Projects" })).toHaveAttribute("aria-current", "page");
  await page.goto("/review");
  await expect(nav.getByRole("link", { name: "Review inbox" })).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link", { name: "Projects" })).not.toHaveAttribute("aria-current", "page");

  const missing = await page.goto("/no-such-page");
  expect(missing?.status()).toBe(404);
  await expect(page.getByTestId("page-not-found")).toContainText("There is no page here");
  await expect(page.getByTestId("page-not-found").getByRole("link", { name: "Projects" })).toHaveAttribute("href", "/");
  await expect(nav).toBeVisible();                                    // the sidebar stays, so the way back is there
  await page.screenshot({ path: test.info().outputPath("not-found.png") });
});
