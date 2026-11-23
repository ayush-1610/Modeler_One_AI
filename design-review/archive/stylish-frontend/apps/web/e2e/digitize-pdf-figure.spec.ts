// R3d (redesign §3.2, the owner's note): the digitizer reads a figure that is an image inside a PDF. The PDF here is
// written by the test: one page with a caption and the same test figure as digitize.spec.ts (three markers at known
// values), placed in a known box. The figure is picked from the PDF's figure list, which crops the page to it; the
// values the server computes from the clicks are checked against the truth, and the dataset keeps the crop.
import { deflateSync } from "node:zlib";

import { expect, test } from "@playwright/test";

import { finishStart } from "./fixtures/inputs";

const W = 800;
const H = 600;
const POINTS = [[125, 300], [150, 350], [200, 400]]; // (1 h, 100), (2 h, 75), (4 h, 50) with the axes below

/** The figure's RGB pixels, row by row: white, with black axes and 9×9 black markers. */
function pixels(): Buffer {
  const out = Buffer.alloc(W * H * 3, 255);
  const dark = (x: number, y: number) =>
    (x === 100 && y >= 100 && y <= 500) || (y === 500 && x >= 100 && x <= 700) ||
    POINTS.some(([px, py]) => Math.abs(x - px) <= 4 && Math.abs(y - py) <= 4);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if (dark(x, y)) out.fill(0, (y * W + x) * 3, (y * W + x) * 3 + 3);
  return out;
}

/** A one-page PDF (600 × 800 pt) with a caption and the figure placed at x 100–500, y 400–700 pt (400 × 300 pt). */
function pdf(): Buffer {
  const image = deflateSync(pixels());
  const content = "BT /F1 12 Tf 72 750 Td (Figure 2. Mean plasma concentrations after a 10 mg dose) Tj ET\n"
    + "q 400 0 0 300 100 400 cm /Im1 Do Q\n";
  const objects: Buffer[] = [
    Buffer.from("<< /Type /Catalog /Pages 2 0 R >>"),
    Buffer.from("<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
    Buffer.from("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Contents 4 0 R "
      + "/Resources << /XObject << /Im1 5 0 R >> /Font << /F1 6 0 R >> >> >>"),
    Buffer.from(`<< /Length ${content.length} >>\nstream\n${content}endstream`),
    Buffer.concat([Buffer.from(`<< /Type /XObject /Subtype /Image /Width ${W} /Height ${H} /ColorSpace /DeviceRGB `
      + `/BitsPerComponent 8 /Filter /FlateDecode /Length ${image.length} >>\nstream\n`), image, Buffer.from("\nendstream")]),
    Buffer.from("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
  ];
  const parts: Buffer[] = [Buffer.from("%PDF-1.4\n")];
  const offsets: number[] = [];
  let at = parts[0].length;
  objects.forEach((body, i) => {
    const chunk = Buffer.concat([Buffer.from(`${i + 1} 0 obj\n`), body, Buffer.from("\nendobj\n")]);
    offsets.push(at);
    parts.push(chunk);
    at += chunk.length;
  });
  const xref = `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
    + offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("")
    + `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${at}\n%%EOF\n`;
  return Buffer.concat([...parts, Buffer.from(xref)]);
}

test("a figure inside a PDF is picked from its figure list, cropped, digitized, and keeps its crop", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: { Authorization: "Bearer dev" },
    multipart: { drug_name: "Figuramide", extract: "false",
                 files: { name: "doe-2019.pdf", mimeType: "application/pdf", buffer: pdf() } },
  });
  expect(started.ok(), await started.text()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  await finishStart(request, projectId);      // Inputs opens once Start is done (page review 1, decision 7)
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: { Authorization: "Bearer dev" } })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/inputs?tab=studies`);
  await page.getByTestId("open-digitizer").click();
  const panel = page.getByTestId("digitizer");
  await expect(panel.getByTestId("figure-list")).toContainText("p.1 · Im1 · 800×600");
  await panel.getByTestId("figure-1-Im1").click();
  const canvas = page.locator(".figure canvas");
  // the page drawn at scale 2 (1200 × 1600) and cropped to the figure's box: the figure's own 800 × 600 pixels
  await expect.poll(async () => canvas.evaluate((c: HTMLCanvasElement) => [c.width, c.height])).toEqual([W, H]);
  await expect(panel.getByTestId("digitize-whole")).toBeVisible();
  const clickAt = async (px: number, py: number) => {
    const box = (await canvas.boundingBox())!;
    await canvas.click({ position: { x: (px * box.width) / W, y: (py * box.height) / H } });
  };

  await clickAt(100, 520); await clickAt(700, 520); await clickAt(80, 500); await clickAt(80, 100);
  const values = panel.getByPlaceholder("value");
  await values.nth(0).fill("0"); await values.nth(1).fill("24"); await values.nth(2).fill("0"); await values.nth(3).fill("200");
  for (const [px, py] of POINTS) await clickAt(px, py);
  await panel.getByPlaceholder("study id (author-year-route-dose)").fill("doe-2019-po-10mg-pdf");
  await panel.getByPlaceholder("reference").fill("Doe 2019, Figure 2");
  await panel.getByPlaceholder("n", { exact: true }).fill("12");
  await panel.getByPlaceholder("dose mg").fill("10");
  await page.screenshot({ path: test.info().outputPath("pdf-figure-cropped.png"), fullPage: true });
  await page.getByTestId("digitize-save").click();

  const card = page.locator(".evidence", { hasText: "doe-2019-po-10mg-pdf" });
  await expect(card).toContainText("cropped to the figure");
  const text = await card.locator(".series").innerText();
  const pairs = [...text.matchAll(/([\d.]+): ([\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
  expect(pairs.length).toBe(3);
  [[1, 100], [2, 75], [4, 50]].forEach(([t, c], i) => {
    expect(Math.abs(pairs[i][0] - t)).toBeLessThan(0.48);
    expect(Math.abs(pairs[i][1] - c)).toBeLessThan(4);
  });
});
