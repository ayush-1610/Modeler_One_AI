// Filling what is missing on Inputs (plan docs/plans/2026-11-14-inputs-task-first.md §3, API 1, 2, 4 and 6): values no
// file links to a study are linked to a new study with a new arm and a new analyte, and later ones to that study with
// another arm (a name that exists is refused in the server's words); a table marked as not data is restored with a
// reason, its answer written into the page with no new read of it; a table no layout reads gets its first layout in the
// layout form, where code's finding on a bad choice is shown beside the column or the setting it names (and, edited as
// text, above it); and compound inputs no source gives yet are filled from their rows, each in the form its value takes
// (a number with its unit, a binding partner by PK-Sim's name, a neutral compound as a statement). Software test data
// (made-up numbers of the made-up Exampleamide), never a model.
import { expect, type APIRequestContext, type Page, test } from "@playwright/test";

import { AUTH, finishStart } from "./fixtures/inputs";

// a profile whose header the rules read (its values belong to no study), and a table no rule reads
const LOOSE = "Time (h),Mean concentration (ng/mL),SD\n0.5,11.5,2.1\n1,24.25,4.4\n2,18.75,3.9\n4,9.5,1.7\n";
const ODD = "Hrs (h),Result (ng/mL)\n0.5,1.2\n1,2.3\n2,3.4\n";
const NEW = "__new__";

type Region = { region_id: string; state: string; mapping_id: string | null; mapping_status: string | null };
type File = { file_id: string; name: string; sha256: string; regions: Region[] };
type Delivery = {
  deliveries: { files: File[] }[]; unassigned: { id: string; file: string | null }[];
  subjects: { subject: string; label: string; arms: { id: string; label: string }[] }[]; analytes: { id: string; label: string }[];
};

async function shot(page: Page, name: string) {
  await page.screenshot({ path: test.info().outputPath(`${name}.png`), fullPage: true });
}

async function project(request: APIRequestContext) {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Exampleamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nOral tablet, 50 mg.") } } });
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: AUTH })).ok()).toBeTruthy();
  return projectId;
}

/** The unassigned values of one file, by the key their link form's test ids carry (the table's extract id). */
function keyOf(page: Delivery, file: string) {
  const value = page.unassigned.find((v) => v.file === file)!;
  return value.id.split("#")[0].replace(/[^A-Za-z0-9-]/g, "-");
}

test("loose values are linked with new arms and an analyte, a table set aside is restored, an unread table gets its first layout",
     async ({ page, request }) => {
  const projectId = await project(request);
  const read = async () => (await (await request.get(`/api/v1/projects/${projectId}/delivery`, { headers: AUTH })).json()).data as Delivery;

  // --- the two files arrive through the head's Add data, and are read by code ---
  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("tab-studies").click();
  await page.getByTestId("client-upload-studies").setInputFiles([
    { name: "loose-profile.csv", mimeType: "text/csv", buffer: Buffer.from(LOOSE) },
    { name: "odd-profile.csv", mimeType: "text/csv", buffer: Buffer.from(ODD) },
  ]);
  await page.getByTestId("tab-files").click();
  const section = page.getByTestId("delivery-section");
  await expect(section.getByTestId("delivery-total-files")).toHaveText("2", { timeout: 120_000 });
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });
  await expect(section.getByTestId("delivery-unassigned")).toBeVisible();
  let delivery = await read();
  const files = delivery.deliveries.flatMap((d) => d.files);
  const odd = files.find((f) => f.name === "odd-profile.csv")!;
  const table = odd.regions[0];
  expect([table.state, table.mapping_id]).toEqual(["unread", null]);

  // --- the loose profile, linked to a new study with a new arm and a new analyte, with the reason ---
  const loose = keyOf(delivery, "loose-profile.csv");
  const group = section.getByTestId(`delivery-unassigned-${loose}`);
  await expect(group.getByTestId(`assign-study-${loose}`)).toHaveAccessibleName(/^Study for the \d+ values of loose-profile\.csv$/);
  await group.getByTestId(`assign-study-${loose}`).selectOption(NEW);
  await group.getByTestId(`assign-new-study-${loose}`).fill("ABC-9");
  await group.getByTestId(`assign-arm-${loose}`).selectOption(NEW);
  await group.getByTestId(`assign-new-arm-${loose}`).fill("Reference");
  await group.getByTestId(`assign-analyte-${loose}`).selectOption(NEW);
  await group.getByTestId(`assign-new-analyte-${loose}`).fill("M1");
  await group.getByTestId(`assign-${loose}-why`).fill("the protocol: study ABC-9, reference arm, metabolite M1");
  await shot(page, "1-link");
  await group.getByTestId(`assign-${loose}-submit`).click();
  await expect(section.getByTestId("delivery-unassigned")).toHaveCount(0);
  delivery = await read();
  const study = delivery.subjects.find((s) => s.label === "ABC-9")!;
  expect(study.arms.map((a) => a.label)).toEqual(["Reference"]);
  const m1 = delivery.analytes.find((a) => a.label === "M1")!;
  expect(m1).toBeTruthy();
  await expect(section.getByTestId(`delivery-subject-${study.subject}`)).toContainText("ABC-9");

  // --- the unread table, marked as not data, then restored with the reason: the page is not read again for it ---
  // a file's tables and texts open under its row in the table of files (slice 2: one row per file)
  const rows = page.getByTestId("files-table");
  await rows.getByTestId(`file-toggle-${odd.name}`).click();
  await rows.getByTestId(`delivery-file-toggle-${odd.file_id}`).click();
  await rows.getByTestId(`delivery-region-aside-${table.region_id}`).click();
  await rows.getByTestId("delivery-region-aside-why").fill("a scratch table, not data");
  await rows.getByTestId("delivery-region-aside-submit").click();
  await expect(rows.getByTestId(`delivery-region-read-${table.region_id}`)).toHaveCount(0);
  await expect(rows.getByTestId(`delivery-region-decision-${table.region_id}`))
    .toContainText(/Marked as not data by .+, \d{4}-\d\d-\d\d \d\d:\d\d: a scratch table, not data/);
  const restore = rows.getByTestId(`delivery-region-restore-${table.region_id}`);
  await expect(restore).toHaveAccessibleName("Restore the table odd-profile of odd-profile.csv");
  await restore.click();
  let pageReads = 0;
  const counting = (r: { method(): string; url(): string }) => { if (r.method() === "GET" && /\/delivery(\?|$)/.test(r.url())) pageReads += 1; };
  page.on("request", counting);
  await rows.getByTestId("delivery-region-restore-why").fill("it is the client's profile after all");
  await rows.getByTestId("delivery-region-restore-submit").click();
  await expect(rows.getByTestId(`delivery-region-decision-${table.region_id}`)).toHaveCount(0);
  await expect(rows.getByTestId(`delivery-region-aside-${table.region_id}`)).toBeVisible();     // not read, as before
  page.off("request", counting);
  expect(pageReads).toBe(0);                                  // the answer was written into the page
  await shot(page, "2-restored");

  // --- "Read this table…": its first layout in the form; a bad choice is shown beside its column ---
  const readIt = rows.getByTestId(`delivery-region-read-${table.region_id}`);
  await expect(readIt).toHaveAccessibleName("Read the table odd-profile of odd-profile.csv");
  await readIt.click();
  const dialog = page.getByTestId("read-table-dialog");
  await expect(dialog).toContainText("sheet odd-profile, cells A1 to B4");
  // what the table holds is chosen before anything is sent: the rules could not tell
  await expect(dialog.getByTestId("read-table-kind")).toHaveValue("");
  await expect(dialog.getByTestId("read-table-needs")).toContainText("Choose what the table holds.");
  await expect(dialog.getByTestId("read-table-role-1")).toHaveAccessibleName("What column 1 holds");
  // at phone width every control stays inside the dialog
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => dialog.locator('[role="dialog"]').evaluate((panel) => {
    const edge = panel.getBoundingClientRect().right;
    return [...panel.querySelectorAll("select, input")].filter((c) => c.getBoundingClientRect().right > edge + 1).length;
  })).toBe(0);
  await page.setViewportSize({ width: 1280, height: 720 });
  await dialog.getByTestId("read-table-kind").selectOption("pk_summary");
  await dialog.getByTestId("read-table-field").selectOption("concentration");
  await dialog.getByTestId("read-table-statistic").selectOption("arithmetic_mean");
  await dialog.getByTestId("read-table-time-unit").fill("h");
  await dialog.getByTestId("read-table-value-unit").fill("ng/mL");
  await dialog.getByTestId("read-table-role-1").selectOption("time");
  await dialog.getByTestId("read-table-role-2").selectOption("ignore");          // the bad choice: no value column, no reason
  await dialog.getByTestId("read-table-missing").fill("NS, 0");                  // and a number as the word for "missing"
  await dialog.getByTestId("read-table-save-why").fill("hours, and the mean level");
  await dialog.getByTestId("read-table-save-submit").click();
  await expect(dialog.getByTestId("read-table-col-2-findings")).toContainText("an ignored column says why its cells are not data");
  await expect(dialog.getByTestId("read-table-columns-findings")).toContainText("no value column");
  await expect(dialog.getByTestId("read-table-col-2")).toHaveClass(/wrong/);
  await expect(dialog).toContainText("a token must not be a number ('0')");      // beside "Missing written as"
  await expect(dialog.locator(".layout-said li").first()).toBeFocused();         // the focus stays in the dialog, on what to fix
  await shot(page, "3-finding");
  await dialog.getByTestId("read-table-role-2").selectOption("value");
  await dialog.getByTestId("read-table-missing").fill("NS");
  await dialog.getByTestId("read-table-save-submit").click();
  // stored as a person's layout that waits for approval; the file is read again with it
  const mapping = page.getByTestId("delivery-mapping-dialog");
  await expect(mapping.getByTestId("mapping-status")).toHaveText("waits for approval");
  await expect(page.getByTestId("read-table-dialog")).toHaveCount(0);
  await shot(page, "4-layout-stored");
  // a correction is made in the same form, the table's headers beside its columns; nothing is stored while code refuses it
  await mapping.getByTestId("mapping-edit-open").click();
  await expect(mapping.getByTestId("mapping-layout-col-1")).toContainText("Hrs (h)");
  await expect(mapping.getByTestId("mapping-layout-role-2")).toHaveValue("value");
  await mapping.getByTestId("mapping-layout-role-2").selectOption("ignore");
  await mapping.getByTestId("mapping-edit-why").fill("the result column is not data");
  await mapping.getByTestId("mapping-edit-submit").click();
  await expect(mapping.getByTestId("mapping-layout-col-2-findings")).toContainText("an ignored column says why its cells are not data");
  await mapping.getByTestId("mapping-layout-text").click();                     // the layout as text, for experts
  await expect(mapping.getByTestId("mapping-spec")).toHaveValue(/"role": "ignore"/);
  // edited as text, every finding is said above the text, a column's with its number; sent again, still said
  await expect(mapping.getByTestId("mapping-layout-findings")).toContainText("Column 2: an ignored column says why its cells are not data");
  await mapping.getByTestId("mapping-edit-submit").click();
  await expect(mapping.getByTestId("mapping-layout-findings")).toContainText("Column 2: an ignored column says why its cells are not data");
  await mapping.getByTestId("mapping-layout-form").click();
  await mapping.getByTestId("mapping-layout-role-2").selectOption("value");
  // when the times are counted from is read in the table: where it is stated is asked for, and checked there
  await mapping.getByTestId("mapping-layout-time-reference").selectOption("first_dose");
  await expect(mapping.getByTestId("mapping-layout-needs")).toContainText("Say where the table states when its times are counted from");
  await expect(mapping.getByTestId("mapping-edit-submit")).toBeDisabled();
  await mapping.getByTestId("mapping-layout-time-reference-at").selectOption("cell");
  await mapping.getByLabel("Where the table states when its times are counted from: the cell's row").fill("1");
  await mapping.getByLabel("Where the table states when its times are counted from: the cell's column").fill("1");
  await mapping.getByTestId("mapping-edit-submit").click();
  await expect(mapping.getByTestId("mapping-layout")).toContainText("the cited text does not state first_dose: 'Hrs (h)'");
  await shot(page, "4b-time-reference");
  await mapping.getByRole("button", { name: "Cancel" }).click();
  await expect(mapping.getByTestId("mapping-status")).toHaveText("waits for approval");
  await mapping.getByTestId("mapping-close").click();
  await expect(section.getByTestId("delivery-running")).toHaveCount(0, { timeout: 120_000 });
  await expect(rows.getByTestId(`delivery-region-mapping-${table.region_id}`)).toContainText("waits for approval");
  await expect(rows.getByTestId(`delivery-region-read-${table.region_id}`)).toHaveCount(0);
  await expect(section.getByTestId("delivery-unassigned")).toBeVisible();

  // --- its values: a new study by a name that exists is refused in the server's words; then that study, a new arm and
  // the analyte named before ---
  delivery = await read();
  const later = keyOf(delivery, "odd-profile.csv");
  const next = section.getByTestId(`delivery-unassigned-${later}`);
  await next.getByTestId(`assign-study-${later}`).selectOption(NEW);
  await next.getByTestId(`assign-new-study-${later}`).fill("abc-9");
  await next.getByTestId(`assign-${later}-why`).fill("the same study, its test arm");
  await next.getByTestId(`assign-${later}-submit`).click();
  await expect(next.getByTestId(`assign-problem-${later}`)).toContainText("ABC-9");
  await next.getByTestId(`assign-study-${later}`).selectOption(study.subject);
  await next.getByTestId(`assign-arm-${later}`).selectOption(NEW);
  await next.getByTestId(`assign-new-arm-${later}`).fill("Test");
  await next.getByTestId(`assign-analyte-${later}`).selectOption(m1.id);
  await next.getByTestId(`assign-${later}-submit`).click();
  await expect(section.getByTestId("delivery-unassigned")).toHaveCount(0);
  delivery = await read();
  expect(delivery.subjects.find((s) => s.subject === study.subject)!.arms.map((a) => a.label)).toEqual(["Reference", "Test"]);
});

test("compound inputs no source gives yet are filled from their rows, each in the form its value takes", async ({ page, request }) => {
  const projectId = await project(request);
  const inputs = async () => (await (await request.get(`/api/v1/projects/${projectId}/inputs`, { headers: AUTH })).json()).data as
    { compound: { id: string; state: string; tab: string; value: number | string | null }[] };
  const row = async (id: string) => (await inputs()).compound.find((r) => r.id === id);
  const before = await inputs();
  for (const id of ["perm.intestinal", "bind.partner", "phys.pka.neutral", "phys.solubility.table"]) {
    expect(before.compound.find((r) => r.id === id)?.state).toBe("empty");
  }
  expect(before.compound.some((r) => /^phys\.pka\.(acid|base)\./.test(r.id))).toBe(false);

  await page.goto(`/projects/${projectId}/inputs?tab=compound`);
  // --- a number with its unit, converted to PK-Sim's ---
  const block = page.getByTestId("block-Permeability and absorption");
  await expect(block.getByTestId("record-perm.intestinal")).toHaveCount(0);                  // folded
  const toggle = block.getByTestId("fill-toggle-Permeability and absorption");
  await expect(toggle).toContainText(/\+ \d+ more you can fill in/);
  await toggle.click();
  const perm = block.getByTestId("record-perm.intestinal");
  await expect(perm).toContainText("no value yet");
  await expect(perm.getByTestId("add-open-perm.intestinal")).toHaveAccessibleName("Add a value for Intestinal permeability");
  await perm.getByTestId("add-open-perm.intestinal").click();
  const form = perm.getByTestId("add-perm.intestinal");
  await form.getByLabel("value for perm.intestinal").fill("0.000015");
  await form.getByLabel("unit for perm.intestinal").fill("cm/s");
  await form.getByLabel("link for perm.intestinal").fill("10.1/perm");
  await form.getByLabel("quote for perm.intestinal").fill("an intestinal permeability of 1.5e-5 cm/s");
  await shot(page, "5-fill");
  await form.getByRole("button", { name: "Add" }).click();
  await expect(page.getByTestId("record-perm.intestinal")).not.toContainText("no value yet");
  await expect.poll(async () => (await row("perm.intestinal"))?.state).not.toBe("empty");
  await shot(page, "6-filled");

  // --- the binding partner, by PK-Sim's name: titled in words, chosen, never typed ---
  const binding = page.getByTestId("block-Binding and partitioning");
  await binding.getByTestId("fill-toggle-Binding and partitioning").click();
  const partner = binding.getByTestId("record-bind.partner");
  await expect(partner.locator(".input-name strong")).toHaveText("Plasma protein binding partner");
  await partner.getByTestId("add-open-bind.partner").click();
  const choose = partner.getByLabel("value for bind.partner");
  await expect(choose.locator("option")).toHaveText(["choose…", "Albumin", "Glycoprotein", "Unknown"]);
  await choose.selectOption("Albumin");
  await partner.getByLabel("source type for bind.partner").selectOption("ASSUMPTION");
  await partner.getByTestId("add-bind.partner").getByRole("button", { name: "Add", exact: true }).click();
  await expect.poll(async () => { const r = await row("bind.partner"); return [r?.state, r?.value]; }).toEqual(["kept", "Albumin"]);

  // --- a neutral compound, stated (no value, no unit); the solubility table is not offered here ---
  const phys = page.getByTestId("block-Identity and physico-chemistry");
  await phys.getByTestId("fill-toggle-Identity and physico-chemistry").click();
  await expect(phys.getByTestId("record-phys.solubility.table")).toHaveCount(0);
  await expect(phys.getByTestId("fill-elsewhere-Identity and physico-chemistry")).toContainText("Solubility vs pH table");
  const neutral = phys.getByTestId("record-phys.pka.neutral");
  await expect(neutral.locator(".input-name strong")).toHaveText("Neutral compound (no pKa)");
  await neutral.getByTestId("add-open-phys.pka.neutral").click();
  await expect(neutral.getByLabel("value for phys.pka.neutral")).toHaveCount(0);
  await expect(neutral.getByLabel("unit for phys.pka.neutral")).toHaveCount(0);
  await neutral.getByLabel("link for phys.pka.neutral").fill("10.1/neutral");
  await neutral.getByLabel("quote for phys.pka.neutral").fill("Exampleamide has no ionizable group");
  await shot(page, "7-neutral");
  await neutral.getByTestId("add-phys.pka.neutral").getByRole("button", { name: "Add", exact: true }).click();
  await expect.poll(async () => (await row("phys.pka.neutral"))?.state).toBe("kept");
  await expect(page.getByTestId("record-phys.pka.neutral").locator(".input-value")).toHaveText("neutral");
});
