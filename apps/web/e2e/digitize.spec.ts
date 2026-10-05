// T-19 / T-45: a person digitizes a published figure. The figure here is drawn by the test with three markers at
// known values, so the values the server computes from the clicks can be checked against the truth.
import { deflateSync } from "node:zlib";

import { expect, test } from "@playwright/test";

const W = 800;
const H = 600;
const POINTS = [[125, 300], [150, 350], [200, 400]]; // (1 h, 100), (2 h, 75), (4 h, 50) with the axes below

function crc32(buf: Buffer): number {
  let c = ~0;
  for (const b of buf) {
    c ^= b;
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
  }
  return ~c >>> 0;
}

function chunk(type: string, data: Buffer): Buffer {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/** A white RGB PNG with black axes and 9×9 black markers. */
function figure(): Buffer {
  const rows: Buffer[] = [];
  const dark = (x: number, y: number) =>
    (x === 100 && y >= 100 && y <= 500) || (y === 500 && x >= 100 && x <= 700) ||
    POINTS.some(([px, py]) => Math.abs(x - px) <= 4 && Math.abs(y - py) <= 4);
  for (let y = 0; y < H; y++) {
    const row = Buffer.alloc(1 + W * 3, 255);
    row[0] = 0;
    for (let x = 0; x < W; x++) if (dark(x, y)) row.fill(0, 1 + x * 3, 4 + x * 3);
    rows.push(row);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(W, 0);
  ihdr.writeUInt32BE(H, 4);
  ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr),
                        chunk("IDAT", deflateSync(Buffer.concat(rows))), chunk("IEND", Buffer.alloc(0))]);
}

test("a figure is digitized against calibrated axes, its overlay approved, and the dataset accepted", async ({ page, request }) => {
  const started = await request.post("/api/v1/projects:initiate", {
    headers: { Authorization: "Bearer dev" },
    multipart: {
      drug_name: "Digitamide", extract: "false",
      files: { name: "doe-2019-figure2.png", mimeType: "image/png", buffer: figure() },
    },
  });
  expect(started.ok()).toBeTruthy();
  const projectId = (await started.json()).data.project_id as string;
  expect((await request.post(`/api/v1/projects/${projectId}/requirements:derive`, { headers: { Authorization: "Bearer dev" } })).ok()).toBeTruthy();

  await page.goto(`/projects/${projectId}/evidence?tab=observed`);
  await page.getByTestId("open-digitizer").click();
  const canvas = page.locator(".figure canvas");
  await expect(canvas).toBeVisible();
  await expect.poll(async () => (await canvas.evaluate((c: HTMLCanvasElement) => c.width))).toBe(W);
  const clickAt = async (px: number, py: number) => {
    const box = (await canvas.boundingBox())!;
    await canvas.click({ position: { x: (px * box.width) / W, y: (py * box.height) / H } });
  };

  const panel = page.getByTestId("digitizer");
  // X1 = 0 h at pixel 100, X2 = 24 h at 700; Y1 = 0 at pixel 500, Y2 = 200 at 100 (the clicks set the mode in order)
  await clickAt(100, 520); await clickAt(700, 520); await clickAt(80, 500); await clickAt(80, 100);
  const values = panel.getByPlaceholder("value");
  await values.nth(0).fill("0"); await values.nth(1).fill("24"); await values.nth(2).fill("0"); await values.nth(3).fill("200");
  for (const [px, py] of POINTS) await clickAt(px, py);

  await panel.getByPlaceholder("study id (author-year-route-dose)").fill("doe-2019-po-10mg");
  await panel.getByPlaceholder("reference").fill("Doe 2019, Figure 2");
  await panel.getByPlaceholder("n", { exact: true }).fill("12");
  await panel.getByPlaceholder("dose mg").fill("10");
  await page.getByTestId("digitize-save").click();

  const card = page.locator(".evidence", { hasText: "doe-2019-po-10mg" });
  await expect(card).toContainText("figure digitized");
  // within the click resolution of the truth (1 h, 100), (2 h, 75), (4 h, 50)
  const text = await card.locator(".series").innerText();
  const pairs = [...text.matchAll(/([\d.]+): ([\d.]+)/g)].map((m) => [Number(m[1]), Number(m[2])]);
  expect(pairs.length).toBe(3);
  [[1, 100], [2, 75], [4, 50]].forEach(([t, c], i) => {
    expect(Math.abs(pairs[i][0] - t)).toBeLessThan(0.48); // 2 % of the 24 h axis
    expect(Math.abs(pairs[i][1] - c)).toBeLessThan(4);    // 2 % of the 200 ng/ml axis
  });
  await page.screenshot({ path: test.info().outputPath("digitized.png"), fullPage: true });
  await card.getByRole("button", { name: "Approve the overlay" }).click();
  await expect(card).toContainText("overlay approved by");
  await card.getByPlaceholder("reason (required)").fill("points match the figure markers");
  await card.getByRole("button", { name: "Accept" }).click();
  await expect(card).toContainText("accepted");
  await expect(page.getByTestId("need-REQ-obs.po_fasted_range")).not.toHaveText("not found");
});
