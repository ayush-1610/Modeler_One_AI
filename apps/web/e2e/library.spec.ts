// The project document library (docs/plans/2026-10-28-project-document-library.md, PR 1): reached from the sidebar of an
// open project, every document with who added it and what the project took from it; searched, filtered and opened.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("the library lists each document with what cites it, and finds, filters and opens one", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Librarimide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nfu was 9 % in human plasma.") } } });
  const projectId = (await started.json()).data.project_id as string;
  const docs = (await (await request.get(`/api/v1/projects/${projectId}/documents`, { headers: AUTH })).json()).data.documents;
  const sha = docs.find((d: { role: string }) => d.role === "proposal").sha256 as string;
  await request.post(`/api/v1/projects/${projectId}/documents`, { headers: AUTH, multipart: {
    role: "annex", files: { name: "annex.md", mimeType: "text/markdown", buffer: Buffer.from("# Annex\nNothing used.") } } });
  // a value read from the proposal, cited to its page
  const fu = await request.post(`/api/v1/projects/${projectId}/evidence`, { headers: AUTH, data: {
    req_id: "REQ-bind.fu", target: "bind.fu", value: 9, unit: "%", source_type: "PUBLICATION", doc_sha256: sha, page: 1,
    quote: "fu was 9 % in human plasma", conditions: { species: "human", matrix: "plasma" } } });
  expect(fu.ok(), await fu.text()).toBeTruthy();

  await page.goto(`/projects/${projectId}/start`);
  await page.getByTestId("nav-library").click();
  await page.waitForURL(/\/library$/);
  const proposal = page.getByTestId("library-row-proposal.md");
  await expect(proposal).toContainText("bind.fu = 9 %");
  await expect(page.getByTestId("library-row-annex.md")).toContainText("Nothing taken from it yet");
  await page.getByTestId("library-search").fill("bind.fu");
  await expect(page.getByTestId("library-row-annex.md")).toHaveCount(0);
  await page.getByTestId("library-search").fill("");
  await page.getByTestId("library-role").selectOption("annex");
  await expect(proposal).toHaveCount(0);
  await page.getByTestId("library-role").selectOption("");
  await page.screenshot({ path: test.info().outputPath("library.png"), fullPage: true });
  await page.getByTestId("library-open-proposal.md").click();
  await expect(page.getByTestId("library-viewer")).toContainText("fu was 9 % in human plasma");
});

test("Add data, from the sidebar at any step, says what each file relates to; a document is withdrawn and restored",
  async ({ page, request }) => {
    // PR 2 of the plan: the owner's answers 10 (Add data above the library), 11 (roles + relates to) and 12 (withdrawn
    // with a reason, never erased, hidden from the agents)
    const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
      drug_name: "Addamide", extract: "false",
      files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal\nAn IR tablet.") } } });
    const projectId = (await started.json()).data.project_id as string;

    await page.goto(`/projects/${projectId}/start`);
    await expect(page.getByTestId("start-files")).toContainText("proposal.md");
    await page.getByTestId("nav-add-data").click();
    const card = page.getByTestId("add-data");
    await expect(card.getByRole("dialog", { name: "Add data" })).toBeVisible();
    await expect(page.getByTestId("add-data-step")).toHaveValue("start");      // the page's own step, preselected
    await page.getByTestId("add-data-files").setInputFiles([
      { name: "f2.json", mimeType: "application/json", buffer: Buffer.from('{"formulation": "F2", "strength_mg": 50}') },
      { name: "pk.csv", mimeType: "text/csv", buffer: Buffer.from("time,conc\n1,2\n") },
    ]);
    await expect(page.getByTestId("add-data-goes-pk.csv")).toHaveValue("client:clinical");   // client data, tagged by its name
    await expect(page.getByTestId("add-data-goes-f2.json")).toHaveValue("doc:annex");
    await page.getByTestId("add-data-goes-f2.json").selectOption("doc:context");             // the guess is switched
    await page.getByTestId("add-data-step").selectOption("inputs");
    await page.getByTestId("add-data-task").fill("Formulations");
    await page.screenshot({ path: test.info().outputPath("add-data.png") });
    await page.getByTestId("add-data-submit").click();
    await expect(page.getByTestId("add-data-done")).toContainText("pk.csv: added as client data");
    await expect(page.getByTestId("add-data-done")).toContainText("f2.json: added as context");
    await page.getByTestId("add-data-close").click();
    await expect(card).toHaveCount(0);
    await expect(page.getByTestId("start-files")).toContainText("f2.json");         // the page behind it is read again

    await page.getByTestId("nav-library").click();
    await page.waitForURL(/\/library$/);
    await expect(page.getByTestId("library-row-f2.json")).toContainText("Inputs");
    await expect(page.getByTestId("library-row-f2.json")).toContainText("Formulations");
    await expect(page.getByTestId("library-row-pk.csv")).toContainText("client file");

    await page.getByTestId("library-withdraw-f2.json").click();
    await expect(page.getByTestId("library-confirm")).toBeDisabled();                // a reason is required
    await page.getByTestId("library-reason").fill("the client sent a corrected formulation sheet");
    await page.getByTestId("library-confirm").click();
    await expect(page.getByTestId("library-withdrawn-f2.json")).toContainText("the client sent a corrected formulation sheet");
    await page.getByTestId("library-status").selectOption("current");
    await expect(page.getByTestId("library-row-f2.json")).toHaveCount(0);
    await page.getByTestId("library-status").selectOption("withdrawn");
    await expect(page.getByTestId("library-row-f2.json")).toBeVisible();             // kept, never erased
    await page.screenshot({ path: test.info().outputPath("library-withdrawn.png"), fullPage: true });
    await page.getByTestId("library-restore-f2.json").click();
    await page.getByTestId("library-reason").fill("withdrawn by mistake");
    await page.getByTestId("library-confirm").click();
    await expect(page.getByTestId("library-row-f2.json")).toHaveCount(0);            // no longer withdrawn
    await page.getByTestId("library-status").selectOption("");
    await expect(page.getByTestId("library-withdrawn-f2.json")).toHaveCount(0);
  });

test("Add data with many files scrolls inside the dialog, not the page behind it", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Scrollamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal") } } });
  const projectId = (await started.json()).data.project_id as string;
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(`/projects/${projectId}/start`);
  await page.getByTestId("nav-add-data").click();
  const card = page.getByTestId("add-data");
  await page.getByTestId("add-data-files").setInputFiles(Array.from({ length: 31 }, (_, i) => (
    { name: `study-${i + 1}-PK Table.csv`, mimeType: "text/csv", buffer: Buffer.from("t,c\n0,0\n") })));
  const dialog = card.getByRole("dialog");
  const box = (await dialog.boundingBox())!;
  expect(box.y + box.height).toBeLessThanOrEqual(720);                         // the panel fits the screen
  const pageTop = await page.evaluate(() => window.scrollY);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.wheel(0, 5000);
  await expect.poll(() => dialog.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);   // the dialog scrolls
  expect(await page.evaluate(() => window.scrollY)).toBe(pageTop);                     // the page behind does not
  await expect(page.getByTestId("add-data-goes-study-31-PK Table.csv")).toBeInViewport();
  await expect(page.getByTestId("add-data-step")).toBeInViewport();
});

test("Add data reads documents for data by default, and a large delivery goes up in batches", async ({ page, request }) => {
  // plan 2026-11-10, R2 (the owner's decision 1): a PDF, Word or Excel document is read for data unless unticked
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Readamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal") } } });
  const projectId = (await started.json()).data.project_id as string;
  await page.goto(`/projects/${projectId}/start`);
  await page.getByTestId("nav-add-data").click();
  const pdf = textPdf("Study 094-26 outlier report: subject 7 excluded from the PK analysis.");
  const sheets = Array.from({ length: 20 }, (_, i) => (
    { name: `study-${i + 1}-PK Table.csv`, mimeType: "text/csv", buffer: Buffer.from(`time,conc\n1,${i + 2}\n`) }));
  await page.getByTestId("add-data-files").setInputFiles([
    { name: "Outlier Report.pdf", mimeType: "application/pdf", buffer: pdf },
    { name: "notes.md", mimeType: "text/markdown", buffer: Buffer.from("# Notes") },
    ...sheets,
  ]);
  await expect(page.getByTestId("add-data-goes-Outlier Report.pdf")).toHaveValue("doc:annex");
  await expect(page.getByTestId("add-data-read-Outlier Report.pdf")).toBeChecked();      // read for data by default
  await expect(page.getByTestId("add-data-read-notes.md")).toHaveCount(0);               // nothing to read in Markdown
  await page.getByTestId("add-data-step").selectOption("inputs");
  await page.getByTestId("add-data-submit").click();
  const done = page.getByTestId("add-data-done");
  await expect(done).toContainText("Outlier Report.pdf: added as an annex; the agent reads it for data on Inputs");
  await expect(done).toContainText("notes.md: added as an annex");
  await expect(done).toContainText("study-1-PK Table.csv");
  await expect(done).toContainText("study-20-PK Table.csv");                               // every batch went up
  const files = (await (await request.get(`/api/v1/projects/${projectId}/client-data`, { headers: AUTH })).json()).data.files;
  expect(files.map((f: { file: string }) => f.file)).toContain("Outlier Report.pdf");
  expect(files.length).toBe(21);
});

/** A one-page PDF with one line of text, its cross-reference table at the right offsets. */
function textPdf(line: string): Buffer {
  const content = `BT /F1 12 Tf 72 720 Td (${line}) Tj ET\n`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${content.length} >>\nstream\n${content}endstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets = objects.map((object, i) => {
    const at = body.length;
    body += `${i + 1} 0 obj\n${object}\nendobj\n`;
    return at;
  });
  const xref = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
    + offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")
    + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${body.length}\n%%EOF\n`;
  return Buffer.from(body + xref, "latin1");
}
