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
// Set once in the runner process, so the workers (which re-read this file) and the specs that seed the read root
// all see the same data directory as the servers.
const DATA = (process.env.E2E_DATA_DIR ??= mkdtempSync(join(tmpdir(), "modeler-e2e-")));
const ENGINE = process.env.E2E_ENGINE_COMMAND ?? `python3 ${REPO}/deploy/dev/stub_engine.py`;
const API_BASE = `http://127.0.0.1:${API_PORT}`;
// With E2E_OIDC_ISSUER set (a test Keycloak with deploy/keycloak/realm-modeler.json imported; its back channel in
// E2E_OIDC_BACKCHANNEL), both servers sign in through Keycloak instead of the DEV sign-in, and only the sign-in flows
// (oidc-*.spec.ts) run. The test Keycloak's self-signed certificate is accepted by the test browser only.
const OIDC = process.env.E2E_OIDC_ISSUER;
const OIDC_BACK = process.env.E2E_OIDC_BACKCHANNEL ?? OIDC;

export default defineConfig({
  testDir: "./e2e",
  ...(OIDC ? { testMatch: /oidc-.*\.spec\.ts/ } : { testIgnore: /oidc-.*\.spec\.ts/ }),
  timeout: 10 * 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    ignoreHTTPSErrors: Boolean(OIDC),
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : {},
  },
  webServer: [
    {
      // The first RDKit import in a fresh environment takes ~20 s and stalls the API while it runs (an extraction job
      // imports it inside the API process), which dropped saves made by whichever spec was running. Load it here, once,
      // before the first request.
      command: `uv run python -c "import rdkit.Chem, rdkit.Chem.Descriptors, rdkit.Chem.rdMolDescriptors" && uv run uvicorn modeler_api.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: REPO,
      url: `${API_BASE}/docs`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        ...(OIDC ? { MODELER_OIDC_ISSUER: OIDC, MODELER_OIDC_JWKS_URL: `${OIDC_BACK}/protocol/openid-connect/certs` }
                 : { MODELER_DEV_AUTH: "1" }),
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
      // any page that always exists: this was /projects/new, which the old-page removal deletes
      url: `http://127.0.0.1:${WEB_PORT}/`,
      // with Keycloak the page redirects to the test Keycloak's sign-in, served with its self-signed certificate
      ignoreHTTPSErrors: Boolean(OIDC),
      timeout: 300_000,
      reuseExistingServer: false,
      env: {
        MODELER_API_BASE: API_BASE,
        ...(OIDC ? { MODELER_OIDC_ISSUER: OIDC, MODELER_OIDC_BACKCHANNEL: OIDC_BACK!, MODELER_WEB_URL: `http://127.0.0.1:${WEB_PORT}` }
                 : { MODELER_WEB_TOKEN: "dev" }),
      },
    },
  ],
});
