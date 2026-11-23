// The web app over HTTPS, for the production deployment: deploy/server/run_modeler.sh starts this when a certificate
// is configured (MODELER_WEB_TLS_*, printed by deploy/server/keycloak.sh env) and `next start` otherwise. Next.js serves
// no HTTPS in production, so this is Next's own request handler behind node:https, with the certificate Keycloak
// serves: the sign-in cookies are then Secure, and no password or token crosses the network in clear.
//
//   MODELER_WEB_TLS_PFX + MODELER_WEB_TLS_PFX_PASSFILE   the PKCS#12 keystore keycloak.sh made, and its password file
//   MODELER_WEB_TLS_CERT + MODELER_WEB_TLS_KEY           or a PEM certificate and key (e.g. from `tailscale cert`)
//   MODELER_WEB_PORT [3000], MODELER_WEB_HOST [0.0.0.0]
import { readFileSync } from "node:fs";
import { createServer } from "node:https";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

import next from "next";

const env = process.env;

function tlsOptions() {
  if (env.MODELER_WEB_TLS_PFX) {
    if (!env.MODELER_WEB_TLS_PFX_PASSFILE) throw new Error("MODELER_WEB_TLS_PFX needs MODELER_WEB_TLS_PFX_PASSFILE");
    return { pfx: readFileSync(env.MODELER_WEB_TLS_PFX),
             passphrase: readFileSync(env.MODELER_WEB_TLS_PFX_PASSFILE, "utf-8").trim() };
  }
  if (env.MODELER_WEB_TLS_CERT && env.MODELER_WEB_TLS_KEY) {
    return { cert: readFileSync(env.MODELER_WEB_TLS_CERT), key: readFileSync(env.MODELER_WEB_TLS_KEY) };
  }
  throw new Error("no certificate: set MODELER_WEB_TLS_PFX (+ _PASSFILE) or MODELER_WEB_TLS_CERT and _KEY");
}

const tls = tlsOptions();
const host = env.MODELER_WEB_HOST || "0.0.0.0";
const port = Number(env.MODELER_WEB_PORT || 3000);
const app = next({ dev: false, dir: dirname(fileURLToPath(import.meta.url)), hostname: host, port });
await app.prepare();
const handle = app.getRequestHandler();
createServer(tls, (req, res) => handle(req, res)).listen(port, host, () => {
  console.log(`web: https://${host}:${port}`);
});
