# Keycloak: sign-in and the electronic-signature step-up (T-06, D10)

`realm-modeler.json` is the `modeler` realm the deployment imports, and `deploy/server/keycloak.sh` runs Keycloak
26.7.5 on the server without sudo. The API checks every token (`modeler_api.auth`: issuer, audience `modeler-api`,
tenant, realm roles, project membership), and a signature needs a fresh step-up (`acr=loa2`, `auth_time` ≤ 300 s).

## What the realm does (tested on Keycloak 26.7.5, 2026-10-13)

- **Sign-in (loa1):** the username and password.
- **Signing (loa2):**
  - Every electronic signature asks for the password and the authenticator code (TOTP) again. The `modeler loa2
    signing` flow has a max age of 0, so nothing is reused (21 CFR 11.200).
  - A person enrols their authenticator app the first time they sign.
- **Tokens for the web app (`modeler-web`, public client, PKCE S256):** they carry `tenant_id`, `projects`, the realm
  roles, `acr`, `auth_time`, and the audience `modeler-api`.
- **The user profile** declares `tenant_id` and `projects` as admin-only attributes. Keycloak drops undeclared
  attributes, and a person must not change their own tenant or projects.
- **What the API checks** is guarded by `services/api/tests/test_keycloak_realm.py`.

## Run it on the server

```bash
cd ~/Modeler_One_AI
bash deploy/server/keycloak.sh install   # Java 21 (conda-forge), Keycloak (checksum checked), a certificate, the realm
bash deploy/server/keycloak.sh admin     # first time only: Keycloak asks YOU for the administrator's password
bash deploy/server/keycloak.sh start
bash deploy/server/keycloak.sh status    # keycloak UP  https://<server>:8443/admin
```

### HTTPS
Keycloak marks its cookies Secure, so browsers can sign in only over HTTPS (plain HTTP works on `localhost` only).
- **By default**, `install` makes a self-signed certificate for the server's address,
  `~/modeler-keycloak/tls/modeler-keycloak.crt`. Trust it once on each computer that signs in:
  - macOS: copy the file over, open it in Keychain Access, then *Trust → Always Trust*;
  - Windows: *Install certificate → Trusted Root Certification Authorities*.
- **Your own certificate** (for example from `tailscale cert`): set `MODELER_KEYCLOAK_CERT` and `MODELER_KEYCLOAK_KEY`
  (PEM) and `MODELER_KEYCLOAK_HOST` to its name before `install` and `start`.
- **The web app's address** must be in *Clients → modeler-web → Valid redirect URIs*. The realm lists `localhost`,
  `127.0.0.1` and `192.168.1.10` on port 3000; add any other address people use, such as a Tailscale name.
- **The local back channel:** HTTP on `127.0.0.1:8080` serves the API's key set and the web server's code exchange. Its
  pages and forms always point at the HTTPS address.

### Users (admin console: `https://<server>:8443/admin`, realm **modeler**)
1. **Users → Add user:** fill in the username, email, first name and last name. Then fill in:
   - **Tenant**: the tenant whose projects they work in;
   - **Project memberships**: the project ids they may open.
2. **Credentials → Set password**, with *Temporary* on. The person chooses their own password at first sign-in.
3. **Role mapping → Assign role → Realm roles:**
   - `modeler-viewer` (read);
   - `modeler-curator` (propose and edit);
   - `modeler-reviewer` (sign);
   - `modeler-qa` (release);
   - `modeler-admin`.

### Then point the stack at it
Run `bash deploy/server/keycloak.sh env`. It prints the lines for `~/.modeler-secrets.env`:
- `MODELER_OIDC_ISSUER`;
- `MODELER_OIDC_JWKS_URL`;
- `MODELER_OIDC_BACKCHANNEL`.

The web app's sign-in and the switch from `pilot` to `production` use them (`deploy/server/_env.sh`).

## Limits, recorded
- **Keycloak's database** is its embedded file database (`--db=dev-file`; Keycloak calls it deprecated for
  production). It holds the users and their authenticator enrolments. Back up
  `~/modeler-keycloak/keycloak-26.7.5/data/` while Keycloak is stopped. Moving to PostgreSQL is a follow-up.
- **Re-running `install` keeps the existing realm** (`--override=false`), so users and their TOTP survive. A later
  change to `realm-modeler.json` therefore does not reach a running realm. Apply it in the admin console, or with a
  partial import.
- **The administrator** created by `keycloak.sh admin` is marked temporary by Keycloak. Create a permanent
  administrator in the `master` realm and delete the temporary one.
