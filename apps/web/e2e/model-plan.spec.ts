// T-50: the P5 canvas. The plan starts as the MS-01 default; a dataset dragged onto a D3 node is checked by the
// validator before the person gives the reason; a rule-breaking move blocks the signature; warnings are acknowledged;
// the MAP is generated from the plan, signed after a confirmation that states what is signed, and the campaign starts
// from it on the Run step, the one start (the owner's decision 2 of 2026-11-11).
import { expect, test } from "@playwright/test";

import { dropEscalations } from "./fixtures/escalations";
import { projectWithInputs } from "./fixtures/inputs";

// The campaign this flow starts may stop for a decision, and the decision pop-up asks for it on every page (the review
// inbox is gone, 2026-11-11): the flow waits for its run to stop, then closes what it left open for the next specs.
test.afterAll(() => dropEscalations());

// The canvas is large: a drag whose target is below the fold makes Playwright scroll mid-drag, and Chromium then
// starts no HTML5 drag at all. A desktop-sized viewport keeps source and target on screen, as for a person.
test.use({ viewport: { width: 1600, height: 1200 } });

test("the plan canvas: drag and drop with reasons, the live validator, approve and sign, run", async ({ page, request }) => {
  const projectId = await projectWithInputs(request, "Planamide", [
    { study_id: "iv-250", route: "iv_infusion", dose_mg: 250 }, { study_id: "iv-500", route: "iv_infusion", dose_mg: 500 },
    { study_id: "po-10", route: "oral", dose_mg: 10 }, { study_id: "po-50", route: "oral", dose_mg: 50 },
    { study_id: "po-100", route: "oral", dose_mg: 100 }, { study_id: "ddi-itra", route: "oral", dose_mg: 50, co_medication: "itraconazole" },
  ]);
  // before the signature the Run step starts nothing: it waits on Review & sign and links there (decision 2)
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("run-blocked")).toContainText("Review & sign is not finished");
  await expect(page.getByTestId("run-blocked").getByTestId("step-blocked-go")).toHaveAttribute("href", `/projects/${projectId}/plan`);
  await expect(page.getByRole("button", { name: "Run campaign" })).toHaveCount(0);

  await page.goto(`/projects/${projectId}/plan`);
  await expect(page.getByTestId("overall-data")).toContainText("Overall Data");
  await expect(page.getByTestId("node-S1")).toContainText("iv-250");          // the MS-01 default
  await expect(page.getByTestId("node-SUPPORTIVE")).toContainText("ddi-itra");
  await expect(page.getByTestId("diff-empty")).toBeVisible();

  // a DDI study dropped on S2 breaks MS-01 rule 4: the validator says so before anything is saved
  await page.getByTestId("overall-data").getByTestId("chip-ddi-itra").dragTo(page.getByTestId("node-S2"));
  await expect(page.getByTestId("move-errors")).toContainText("rule 4");
  await page.getByRole("button", { name: "Cancel" }).click();

  // a valid move, onto the arrow leading into S5, with its reason
  await page.getByTestId("edge-S4-S5").scrollIntoViewIfNeeded();   // the arrow in view first: a drag that scrolls drops nothing
  await page.getByTestId("overall-data").getByTestId("chip-po-10").dragTo(page.getByTestId("edge-S4-S5"));
  await expect(page.getByTestId("move-ok")).toBeVisible();
  await page.getByTestId("move-reason").fill("the low dose is kept to validate the dose range externally");
  await page.getByTestId("move-confirm").click();
  await expect(page.getByTestId("node-S5")).toContainText("po-10");
  await expect(page.getByTestId("diff-po-10")).toContainText("the low dose is kept");
  await expect(page.getByTestId("node-S5").getByTestId("chip-po-10")).toContainText("🔒");

  // D1: the renal pathway's parameter is freed in S1 within bounds, with the reason (a person's choice, locked)
  await page.getByRole("button", { name: "D1 · disposition" }).click();
  await expect(page.getByTestId("pathway-GlomerularFiltration")).toBeVisible();
  await page.getByTestId("fit-elim.renal.gfr_fraction").click();
  const form = page.getByTestId("fit-form-elim.renal.gfr_fraction");
  await form.getByPlaceholder("why (required)").fill("the renal share of clearance is uncertain");
  await form.getByRole("button", { name: "Save" }).click();
  await expect(page.getByTestId("param-elim.renal.gfr_fraction")).toContainText("fitted in S1");
  await expect(page.getByTestId("diff-elim.renal.gfr_fraction")).toContainText("renal share");
  await page.getByRole("button", { name: "D3 · development and validation" }).click();
  await expect(page.getByTestId("node-S1")).toContainText("elim.renal.gfr_fraction");

  // the ICH M15 model risk is the person's, never assumed: until it is set the plan cannot be signed
  await expect(page.getByTestId("violation-risk:model_risk")).toContainText("never assumed");
  const settings = page.getByTestId("risk-and-budget");
  await settings.getByLabel("Model risk (ICH M15)").selectOption("medium");
  await settings.getByLabel("Why this risk").fill("medium model influence, medium decision consequence");
  await settings.getByRole("button", { name: "Set risk" }).click();
  await expect(page.getByTestId("violation-risk:model_risk")).toHaveCount(0);
  await expect(settings.getByLabel("Time budget (hours)")).toHaveValue("8");    // the platform default, split by MS-01

  // warnings are acknowledged with a reason; then the validator is green and "Sign the plan (MAP)" is enabled
  const sign = page.getByTestId("approve-and-sign");
  for (let i = 0; i < 6 && !(await page.getByTestId("validator-green").isVisible()); i++) {
    const warning = page.locator("[data-testid^='violation-']").first();
    const id = (await warning.getAttribute("data-testid"))!;
    await warning.getByPlaceholder("accept it because…").fill("an accepted limitation of this test project");
    await warning.getByRole("button", { name: "Acknowledge" }).click();
    // an acknowledged warning leaves the open list: wait for that, not a fixed time (a slow answer made the next pass
    // fill the warning just acknowledged, which then vanished)
    await expect(page.getByTestId(id)).toHaveCount(0);
  }
  await expect(page.getByTestId("validator-green")).toBeVisible();
  await expect(sign).toBeEnabled();
  await expect(sign).toHaveText("Sign the plan (MAP)");
  await page.screenshot({ path: test.info().outputPath("plan.png"), fullPage: true });

  // the signature is confirmed first, saying what is signed and what it means; Cancel signs nothing
  await sign.click();
  const confirm = page.getByTestId("sign-confirm-dialog");
  await expect(confirm.getByTestId("sign-confirm-what")).toContainText("MAP v1 for Planamide");
  await expect(confirm.getByTestId("sign-confirm-what")).toContainText("Approved");
  await expect(confirm.getByTestId("sign-confirm-what")).toContainText("step-up");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByTestId("map-signed")).toHaveCount(0);

  // a refused signature is an error, read aloud (role=alert), never a green note. The refusal is the API's own answer
  // shape, returned for this one request so the refusal is certain; the next attempt goes to the API.
  await page.route("**/plan:sign", (route) => route.fulfill({ status: 409, contentType: "application/json",
                                                               body: JSON.stringify({ detail: "the validator has an open violation" }) }), { times: 1 });
  await sign.click();
  await page.getByTestId("sign-confirm").click();
  await expect(page.getByTestId("plan-message")).toHaveAttribute("role", "alert");
  await expect(page.getByTestId("plan-message")).toHaveClass(/\berr\b/);
  await expect(page.getByTestId("plan-message")).toContainText("The MAP was not signed: the validator has an open violation");
  await expect(page.getByTestId("map-signed")).toHaveCount(0);

  await sign.click();
  await page.getByTestId("sign-confirm").click();
  await expect(page.getByTestId("map-signed")).toContainText("MAP v1 signed");
  await expect(page.getByTestId("plan-message")).toHaveAttribute("role", "status");

  // D-14: after the signature a move is a MAP deviation — recorded, then signed into MAP v2, before the run
  // the canvas in view first, as a person would have it: the taller page head (plan 2026-11-06 §5) left the signature
  // button, and so the view after signing, above the canvas, and a drag that has to scroll the page drops nothing
  await page.getByTestId("node-S2").scrollIntoViewIfNeeded();
  await page.getByTestId("overall-data").getByTestId("chip-po-10").dragTo(page.getByTestId("node-S2"));
  await expect(page.getByTestId("move-ok")).toBeVisible();
  await expect(page.getByTestId("move-deviation")).toContainText("MAP deviation");
  await page.getByTestId("move-reason").fill("the external dose range is covered by po-50; po-10 trains absorption");
  await page.getByTestId("move-confirm").click();
  await expect(page.getByTestId("deviations-pending")).toContainText("po-10");
  await expect(page.getByTestId("go-to-run")).toHaveCount(0);              // nothing runs on an unsigned deviation
  await expect(sign).toHaveText("Sign the deviation (1)");
  // nor on the Run step: it says what Review & sign still waits on and links back
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByTestId("run-blocked").getByTestId("step-blocked-go")).toHaveAttribute("href", `/projects/${projectId}/plan`);
  await expect(page.getByRole("button", { name: "Run campaign" })).toHaveCount(0);
  await page.getByTestId("run-blocked").getByTestId("step-blocked-go").click();
  await page.waitForURL(/\/plan$/);
  await sign.click();
  await expect(page.getByTestId("sign-confirm-what")).toContainText("1 MAP deviation for Planamide into MAP v2, which supersedes MAP v1");
  await expect(page.getByTestId("sign-confirm-dialog")).toContainText("po-10");
  await page.getByTestId("sign-confirm").click();
  await expect(page.getByTestId("map-signed")).toContainText("MAP v2 signed");
  await expect(page.getByTestId("map-signed")).toContainText("supersedes");
  // the plan has no run button of its own: it links to the Run step, whose one start runs from the signed MAP v2
  // (this used to click a second "Run the campaign (P6)" button here; decision 2 of 2026-11-11 leaves one start)
  await page.getByTestId("go-to-run").click();
  await page.waitForURL(new RegExp(`/projects/${projectId}$`));
  await expect(page.getByTestId("run-from-map")).toContainText("MAP v2");
  await page.getByRole("button", { name: "Run campaign" }).click();
  await page.waitForURL(/\/campaigns\/[^/]+$/);
  await expect(page.getByRole("heading", { name: "Planamide" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("campaign-status")).toHaveText(/completed|escalated|awaiting_signature|aborted|failed/,
                                                               { timeout: 8 * 60_000 });
});
