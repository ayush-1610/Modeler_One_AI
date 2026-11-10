// Large deliveries through the web server's /api proxy (next.config.mjs): the owner's 17-file "Add data" upload came
// back as a bare HTTP 500 because Next's proxy capped the body at 10 MB and gave up on the API after 30 s.
import { expect, test } from "@playwright/test";

import { AUTH } from "./fixtures/inputs";

test("an upload over 10 MB reaches the API through the web server", async ({ request }) => {
  const started = await request.post("/api/v1/projects:initiate", { headers: AUTH, multipart: {
    drug_name: "Bulkamide", extract: "false",
    files: { name: "proposal.md", mimeType: "text/markdown", buffer: Buffer.from("# Proposal") } } });
  const projectId = (await started.json()).data.project_id as string;
  const big = Buffer.alloc(14 * 1024 * 1024, "annex text line\n");
  const res = await request.post(`/api/v1/projects/${projectId}/documents`, { headers: AUTH, timeout: 120_000,
    multipart: { role: "annex", files: { name: "big-annex.txt", mimeType: "text/plain", buffer: big } } });
  expect(res.status(), await res.text()).toBeLessThan(300);
});
