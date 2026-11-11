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
   - **Project memberships** (optional): project ids they may open besides their own. A project made in the web opens
     to its creator, who adds colleagues in the project page's *Members* panel once they have signed in once. Use
     this attribute only for projects made before that, or outside the web.
2. **Credentials → Set password**, with *Temporary* on. The person chooses their own password at first sign-in.
3. **Role mapping → Assign role → Realm roles:**
   - `modeler-viewer` (read);
   - `modeler-curator` (propose and edit);
   - `modeler-reviewer` (sign);
   - `modeler-qa` (release);
   - `modeler-admin`.

### The web app's sign-in (`apps/web/lib/oidc.ts`)
With `MODELER_OIDC_ISSUER` set, the web signs people in through Keycloak:
- the tokens are kept in httpOnly cookies, and `apps/web/proxy.ts` adds the person's own token to every API call;
- a signature the API refuses for want of a step-up opens a dialog, and Keycloak asks for the password and the
  authenticator code in a small window;
- `MODELER_WEB_URL` must be the address people open, because sign-in returns to `<it>/auth/callback`.

Unset, the web keeps the DEV sign-in.

### Then switch the server to production
`bash deploy/server/keycloak.sh env` prints the lines that turn Keycloak sign-in on:
- the realm: `MODELER_OIDC_ISSUER`, `MODELER_OIDC_JWKS_URL` and `MODELER_OIDC_BACKCHANNEL`;
- the web's address: `MODELER_WEB_URL`, over HTTPS;
- its certificate: `MODELER_WEB_TLS_*`, the same one Keycloak serves.

```bash
bash deploy/server/postgres.sh env >> ~/.modeler-secrets.env    # once: the Part 11 records go to PostgreSQL too
bash deploy/server/keycloak.sh env >> ~/.modeler-secrets.env    # once; check the file afterwards (chmod 600)
bash deploy/server/stop_modeler.sh && bash deploy/server/run_modeler.sh
bash deploy/server/status_modeler.sh   # deployment: production (Keycloak sign-in); keycloak UP; web UP (https)
curl -s localhost:8000/health          # {"status":"ok","deployment":"production","verifier":"oidc"}
```

With `MODELER_OIDC_ISSUER` in the secrets file, `deploy/server/_env.sh` runs the stack as **production**:
- the API refuses the DEV verifier, and refuses to start unless its Part 11 records also go to PostgreSQL
  (`MODELER_PART11_STORE=postgres`, from `postgres.sh env`; install PostgreSQL first, below);
- every signature is a Part 11 signature;
- `run_modeler.sh` starts Keycloak with the stack, and `apps/web/server.mjs` serves the web over HTTPS at
  `https://<server>:3000`.

To go back to the pilot, remove those lines and restart. A pilot's DEV signatures stay marked as not Part 11.

### Keycloak's database: PostgreSQL (`deploy/server/postgres.sh`)
Keycloak starts on its embedded file database. Keycloak calls that deprecated for production, so move it to
PostgreSQL, which the same server runs without sudo:
```bash
bash deploy/server/postgres.sh install        # PostgreSQL 16 (conda-forge), roles, databases, the platform's schema
bash deploy/server/postgres.sh env >> ~/.modeler-secrets.env   # Keycloak's database and the Part 11 store
source ~/.modeler-secrets.env
bash deploy/server/keycloak.sh migrate-db     # realms, users and their authenticators, from the file database
bash deploy/server/stop_modeler.sh && bash deploy/server/run_modeler.sh
bash deploy/server/install_autostart.sh       # once: adds the nightly backup and its restore check (02:17)
```
- **On a new server,** install PostgreSQL and set `MODELER_KEYCLOAK_DB=postgres` before `keycloak.sh install`; then
  there is nothing to migrate.
- **What `postgres.sh` sets up:**
  - it listens on `127.0.0.1` only;
  - every password is random, kept in a mode-600 file under `~/modeler-postgres/secrets`, and typed by nobody;
  - the API's login cannot change or remove a row of the Part 11 tables (audit events, signatures);
  - each migration runs once, recorded with its sha256.
- **Backups** go to `~/modeler-backups/<date>`; set `MODELER_BACKUP_DIR` to put them on another disk. Each is restored
  into scratch databases every night to prove it is complete (`~/modeler-logs/backup.log`).
- **The Part 11 records** (production): every audit event is copied into PostgreSQL before its file line is
  written, with the file chain's own hashes; the pilot's earlier events are copied first. Every signature becomes a
  row. The API's login cannot change or remove either. `bash deploy/server/postgres.sh verify` (nightly too) checks
  the database copy against the file chains, so a file chain rewritten after the fact shows up
  (`docs/plans/2026-10-15-part11-records-postgres.md`).

## Going live on the server with its Tailscale name (adt-server, 2026-11-10)

The order that takes a pilot server (DEV sign-in, no PostgreSQL, no Keycloak) to Keycloak sign-in under its Tailscale
name. That name gets a certificate every browser trusts (`tailscale cert`), and it stays the same when the LAN address
changes. Every person who uses the app must then be on the tailnet.

0. **In the Tailscale admin console** (once): *DNS* → turn on **MagicDNS** and **HTTPS Certificates**.
1. **PostgreSQL** (production keeps the Part 11 records there, and Keycloak's database):
   ```bash
   cd ~/Modeler_One_AI
   ls ~/modeler-data/read-root/                    # the companies: the DEV sign-in's is `dev`
   bash deploy/server/postgres.sh install
   bash deploy/server/postgres.sh status           # postgres UP  127.0.0.1:5432
   bash deploy/server/postgres.sh env >> ~/.modeler-secrets.env && chmod 600 ~/.modeler-secrets.env
   ```
2. **The certificate**, for the server's Tailscale name:
   ```bash
   TS=tailscale; [ -x ~/tailscale/tailscale ] && TS="$HOME/tailscale/tailscale --socket=$HOME/.tailscale-state/tailscaled.sock"
   NAME=$($TS status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
   echo "$NAME"                                    # adt-server.<your-tailnet>.ts.net
   mkdir -p ~/modeler-keycloak/tls && chmod 700 ~/modeler-keycloak/tls
   $TS cert --cert-file ~/modeler-keycloak/tls/tailscale.crt --key-file ~/modeler-keycloak/tls/tailscale.key "$NAME"
   chmod 600 ~/modeler-keycloak/tls/tailscale.key
   printf 'export MODELER_KEYCLOAK_HOST=%s\nexport MODELER_KEYCLOAK_CERT=%s\nexport MODELER_KEYCLOAK_KEY=%s\n' \
     "$NAME" ~/modeler-keycloak/tls/tailscale.crt ~/modeler-keycloak/tls/tailscale.key >> ~/.modeler-secrets.env
   ```
   - **`NAME` is empty:** the server is signed out of Tailscale (`$TS status` says `NeedsLogin`; a machine's login
     expires). Run `$TS up --hostname=adt-server`, open the link it prints on a computer signed in to the same
     tailnet, then turn off key expiry for the machine (Tailscale admin console → *Machines* → ⋯ → *Disable key
     expiry*).
   - **`cert` answers `no TailscaleVarRoot`:** tailscaled was started with `--state` (before `setup_tailscale.sh`
     used `--statedir`) and has no folder for certificates. Restart it with `--statedir` (the login is kept) and run
     `bash deploy/server/setup_tailscale.sh` once to update its `@reboot` entry:
     ```bash
     setsid bash -c 'pkill -x tailscaled; sleep 2; nohup ~/tailscale/tailscaled --tun=userspace-networking --statedir=$HOME/.tailscale-state --socket=$HOME/.tailscale-state/tailscaled.sock >> ~/modeler-logs/tailscaled.log 2>&1 &'
     ```
   - **Write the three lines only after `cert` succeeds**: lines naming a certificate that is not there stop
     Keycloak from starting (`MODELER_KEYCLOAK_CERT / _KEY are not readable`).
3. **Keycloak**, on PostgreSQL from the start (`MODELER_KEYCLOAK_DB=postgres`, from step 1):
   ```bash
   bash deploy/server/keycloak.sh install   # imports the realm with https://$NAME:3000/* as a sign-in return address
   bash deploy/server/keycloak.sh admin     # Keycloak asks YOU for its administrator's password
   bash deploy/server/keycloak.sh start
   bash deploy/server/keycloak.sh status    # keycloak UP  https://$NAME:8443/admin  realm modeler
   ```
4. **Your account**, in `https://$NAME:8443/admin`, realm **modeler**: *Users → Add user*. Enter the username, email,
   first name and last name. Set **Tenant** (`tenant_id`) to the company folder from step 1, `dev`. Then:
   - *Credentials → Set password*, with Temporary on;
   - *Role mapping → Assign role → Realm roles*: `modeler-viewer`, `modeler-curator`, `modeler-reviewer`,
     `modeler-qa`, `modeler-admin`.
5. **Switch the stack to Keycloak** (production):
   ```bash
   bash deploy/server/keycloak.sh env >> ~/.modeler-secrets.env && chmod 600 ~/.modeler-secrets.env
   grep -q MODELER_MASTER_KEY ~/.modeler-secrets.env || echo "export MODELER_MASTER_KEY=$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')" >> ~/.modeler-secrets.env
   bash deploy/server/stop_modeler.sh && bash deploy/server/run_modeler.sh
   bash deploy/server/status_modeler.sh     # deployment: production (Keycloak sign-in) ... open: https://$NAME:3000
   curl -s localhost:8000/health            # {"status":"ok","deployment":"production","verifier":"oidc"}
   bash deploy/server/install_autostart.sh  # once: nightly backups and their restore check
   ```
6. **Sign in** at `https://$NAME:3000`: use the temporary password, then choose your own.
   - The computer must be on the tailnet, with the Tailscale app's *Use Tailscale DNS settings* on. A browser that
     answers "can't find the server" is not resolving the name: check with `dscacheutil -q host -a name $NAME` on a
     Mac (it should answer the server's `100.x` address). Safari's iCloud Private Relay can bypass Tailscale's DNS;
     another browser, or turning Private Relay off, settles it.
7. **Your projects:** the projects made under the DEV sign-in belong to its `dev-user`.
   - In *Admin console → Companies → dev → Give a person projects*, choose yourself, "every project of this company",
     and a reason.
   - The step-up asks for your password and authenticator code. The first time, it shows a QR code for the
     authenticator app.
8. **The certificate lasts 90 days.** Renew it each month with step 2's `$TS cert …` line, then
   `bash deploy/server/stop_modeler.sh && bash deploy/server/run_modeler.sh`.

## Limits, recorded
- **Re-running `install` keeps the existing realm** (`--override=false`), so users and their TOTP survive. A later
  change to `realm-modeler.json` therefore does not reach a running realm. Apply it in the admin console, or with a
  partial import.
- **The administrator** created by `keycloak.sh admin` is marked temporary by Keycloak. Create a permanent
  administrator in the `master` realm and delete the temporary one.
