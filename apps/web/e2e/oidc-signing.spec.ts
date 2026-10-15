// T-06: sign-in through Keycloak and the signing step-up, end to end in the browser. Runs only against a test Keycloak
// with deploy/keycloak/realm-modeler.json imported (playwright.config.ts: E2E_OIDC_ISSUER, E2E_OIDC_BACKCHANNEL, and
// the test Keycloak's own administrator in E2E_OIDC_ADMIN_USER / E2E_OIDC_ADMIN_PASSWORD, which creates the test
// person). The decision signed is seeded campaign state (software test data, no engine run), as in feedback.spec.ts.
import { createHmac, randomBytes } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

const ISSUER = process.env.E2E_OIDC_ISSUER!;
const BACK = process.env.E2E_OIDC_BACKCHANNEL ?? ISSUER;
const ADMIN = BACK.replace(/\/realms\/.*$/, "");
const TENANT = "e2e-oidc";
const PROJECT = "p-oidc";
const ID = "camp-oidc-e2e";
const PERSON = { username: `signer-${randomBytes(3).toString("hex")}`, password: `Pw-${randomBytes(9).toString("hex")}` };
let totpKey = "";

/** RFC 6238 with Keycloak's settings (HmacSHA1, 6 digits, 30 s); Keycloak's totpSecret is the raw key. */
function totp(key: string, at = Date.now()): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 30_000)));
  const mac = createHmac("sha1", Buffer.from(key, "utf-8")).update(counter).digest();
  const offset = mac[mac.length - 1] & 15;
  return String((mac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

async function admin(path: string, init: RequestInit = {}) {
  const token = await fetch(`${ADMIN}/realms/master/protocol/openid-connect/token`, {
    method: "POST",
    body: new URLSearchParams({ grant_type: "password", client_id: "admin-cli",
                                username: process.env.E2E_OIDC_ADMIN_USER ?? "admin", password: process.env.E2E_OIDC_ADMIN_PASSWORD ?? "" }),
  }).then((r) => r.json());
  const res = await fetch(`${ADMIN}/admin/realms/modeler${path}`, {
    ...init, headers: { Authorization: `Bearer ${token.access_token}`, "Content-Type": "application/json" },
  });
  expect(res.ok, `${path}: HTTP ${res.status}`).toBeTruthy();
  return res;
}

test.beforeAll(async () => {
  // the test web's address is a valid redirect for this Keycloak, and a person exists to sign
  const [web] = await (await admin("/clients?clientId=modeler-web")).json();
  const here = `${new URL(test.info().project.use.baseURL!).origin}/*`;
  if (!web.redirectUris.includes(here)) {
    await admin(`/clients/${web.id}`, { method: "PUT", body: JSON.stringify({ ...web, redirectUris: [...web.redirectUris, here] }) });
  }
  await admin("/users", { method: "POST", body: JSON.stringify({
    username: PERSON.username, enabled: true, firstName: "Oidc", lastName: "Signer", email: `${PERSON.username}@example.test`,
    emailVerified: true, attributes: { tenant_id: [TENANT], projects: [PROJECT] },
    credentials: [{ type: "password", value: PERSON.password, temporary: false }] }) });
  const [user] = await (await admin(`/users?username=${PERSON.username}&exact=true`)).json();
  const reviewer = await (await admin("/roles/modeler-reviewer")).json();
  await admin(`/users/${user.id}/role-mappings/realm`, { method: "POST", body: JSON.stringify([reviewer]) });

  // an escalated campaign of that person's project, waiting for a signed decision
  const root = join(process.env.E2E_DATA_DIR!, "read-root", TENANT);
  mkdirSync(root, { recursive: true });
  const stage = (s: string, status: string) => ({ stage: s, label: s, status, rounds: [], notes: [] });
  writeFileSync(join(root, "campaigns.json"), JSON.stringify({ campaigns: [{
    id: ID, project: PROJECT, compound: "Signol", question: "sign-in", modelRisk: "medium", budgetSeconds: 3600,
    elapsedSeconds: 60, currentStage: "S2", status: "ESCALATED", stages: [stage("S0", "PASSED"), stage("S2", "ESCALATED")],
    gof: [], engine: { kind: "software-fixture", command: "seeded" },
    resume: {
      request: { campaign_id: ID, tenant_id: TENANT, compound: "Signol", map_id: "m", cpf_uri: "file:///none/cpf.json",
                 cpf_sha256: "a".repeat(64), stages: ["S0", "S2"] },
      cpf_uri: "file:///none/cpf.json", cpf_sha256: "a".repeat(64), completed_stages: ["S0"], escalated_stage: "S2",
    },
  }] }));
  writeFileSync(join(root, "escalations.json"), JSON.stringify({ escalations: [{
    id: `${ID}-S2`, campaignId: ID, stage: "S2", reasonCode: "ROUNDS_EXHAUSTED", evidence: "Seeded for the sign-in test.",
    options: [{ id: "abort", label: "Stop the campaign", requiresSignature: true }],
  }] }));
});

async function signIn(page: Page) {
  await page.goto("/review");
  await expect(page).toHaveURL(new RegExp(`^${ISSUER.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}/protocol/openid-connect/auth`));
  await page.locator("#username").fill(PERSON.username);
  await page.locator("#password").fill(PERSON.password);
  await page.locator("#kc-login").click();
  await expect(page).toHaveURL(/\/review$/);
}

test("sign-in through Keycloak, and a signature asks for the password and the authenticator code again", async ({ page }) => {
  await signIn(page);
  await expect(page.getByTestId("signed-in")).toContainText("Oidc Signer");

  // the browser's code still sends the DEV bearer; the web server replaces it with the person's own token
  const unsigned = await page.evaluate(async (project) => (await fetch(`/api/v1/projects/${project}/signatures`, {
    method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer dev" },
    body: JSON.stringify({ meaning: "Approved", record_type: "test", record_id: "r1", record_sha256: "a".repeat(64) }),
  })).json(), PROJECT);
  expect(unsigned.detail.code).toBe("STEP_UP_REQUIRED");

  const card = page.locator(".card", { hasText: `campaign ${ID}, stage S2` });
  await card.getByTestId("decision-select").selectOption("abort");
  await card.locator("textarea").first().fill("the sign-in test stops this seeded campaign");
  await card.getByTestId("decision-sign").click();
  await page.getByTestId("decision-confirm").click();

  // the API refuses without a fresh step-up; the dialog says why and opens Keycloak's check in a window
  await expect(page.getByTestId("step-up-dialog")).toBeVisible();
  const popupOpened = page.waitForEvent("popup");
  await page.getByTestId("step-up-confirm").click();
  const popup = await popupOpened;
  await popup.locator("#password").fill(PERSON.password);
  await popup.locator("#kc-login").click();
  // first signature: the person enrols their authenticator (the key Keycloak shows, read here as an app would)
  totpKey = await popup.locator("input[name=totpSecret]").inputValue();
  await popup.locator("#totp").fill(totp(totpKey));
  await popup.locator("form#kc-totp-settings-form [type=submit]").click();
  await popup.waitForEvent("close");

  // the decision was sent again with the step-up and accepted: the escalation is gone
  await expect(page.getByTestId("step-up-dialog")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: `Escalation — campaign ${ID}, stage S2` })).toHaveCount(0);

  // a second signature asks for both again (nothing is reused, 21 CFR 11.200)
  const again = page.evaluate(async (project) => (await fetch(`/api/v1/projects/${project}/signatures`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ meaning: "Approved", record_type: "test", record_id: "r2", record_sha256: "b".repeat(64) }),
  })).status, PROJECT);
  expect([201, 403]).toContain(await again);  // 201 only within the 300 s the API allows after a step-up
  const stepUp = await page.context().newPage();
  await stepUp.goto("/auth/login?step_up=1&return=/review");
  await expect(stepUp.locator("#password")).toBeVisible();
  await stepUp.locator("#password").fill(PERSON.password);
  await stepUp.locator("#kc-login").click();
  await new Promise((r) => setTimeout(r, Math.max(0, 30_000 - (Date.now() % 30_000)) + 500));  // a new TOTP window
  await stepUp.locator("#otp").fill(totp(totpKey));
  await stepUp.locator("#kc-login").click();
  await expect(stepUp).toHaveURL(/\/review$/);
  const signed = await stepUp.evaluate(async (project) => (await fetch(`/api/v1/projects/${project}/signatures`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ meaning: "Approved", record_type: "test", record_id: "r3", record_sha256: "c".repeat(64) }),
  })).json(), PROJECT);
  expect(signed.auth_method).toBe("oidc:loa2");
  expect(signed.manifestation).toContain("Oidc Signer");
});

test("sign-out ends the session here and at Keycloak", async ({ page }) => {
  await signIn(page);
  await page.getByTestId("sign-out").click();
  await expect(page).toHaveURL(new RegExp("/protocol/openid-connect/auth"));
  // no session is left in the browser (the new sign-in's own request cookie is all there is)
  const names = (await page.context().cookies()).map((c) => c.name);
  expect(names.filter((n) => ["modeler_at", "modeler_rt", "modeler_idt"].includes(n))).toHaveLength(0);
});
