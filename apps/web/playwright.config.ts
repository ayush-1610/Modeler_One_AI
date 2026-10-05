// Playwright acceptance flows (T-26/T-28): the browser drives the real web app against the real API.
//
//   npm --prefix apps/web run e2e                      # stub engine: proves the software path only
//   E2E_ENGINE_COMMAND="Rscript $PWD/services/engine-worker/r/run_job.R" npm --prefix apps/web run e2e   # PK-Sim
//
// Both servers are started here on their own ports with a fresh data directory, so a run never touches a live
// deployment's projects. The stub engine (deploy/dev/stub_engine.py) is a software fixture: a flow that passes on
// it proves UI → API → runner → monitor works, and nothing about the pharmacology.
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { defineConfig } from "@playwright/test";

const REPO = resolve(__dirname, "../..");
const API_PORT = Number(process.env.E2E_API_PORT ?? 8011);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3011);
const DATA = process.env.E2E_DATA_DIR ?? mkdtempSync(join(tmpdir(), "modeler-e2e-"));
const ENGINE = process.env.E2E_ENGINE_COMMAND ?? `python3 ${REPO}/deploy/dev/stub_engine.py`;
const API_BASE = `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 10 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {},
  },
  webServer: [
    {
      command: `uv run uvicorn modeler_api.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: REPO,
      url: `${API_BASE}/docs`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        MODELER_DEV_AUTH: "1",
        MODELER_EXECUTION_BACKEND: "local",
        MODELER_READ_ROOT: join(DATA, "read-root"),
        MODELER_OBJECT_STORE_URI: `file://${join(DATA, "objstore")}`,
        MODELER_ENGINE_COMMAND: ENGINE,
        MODELER_FIT_WORKERS: process.env.MODELER_FIT_WORKERS ?? "2",
      },
    },
    {
      // Rewrites are fixed at build time, so the build must see the test API's address.
      command: `npm run build && npx next start -H 127.0.0.1 -p ${WEB_PORT}`,
      cwd: __dirname,
      url: `http://127.0.0.1:${WEB_PORT}/projects/new`,
      timeout: 300_000,
      reuseExistingServer: false,
      env: { MODELER_API_BASE: API_BASE, MODELER_WEB_TOKEN: "dev" },
    },
  ],
});
