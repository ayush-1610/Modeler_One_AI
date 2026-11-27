#!/usr/bin/env bash
# Keycloak for the single-node deployment (T-06 / D10): sign-in, and the step-up every electronic signature asks for.
# No sudo: Java 21 comes from conda-forge (this server's ~/miniforge3) and Keycloak from Maven Central, both under
# ~/modeler-keycloak. Passwords are typed only into Keycloak's own prompts and pages; this script never asks for one.
#
#   keycloak.sh install   Java 21 + Keycloak (checksum checked), a TLS certificate, the realm (deploy/keycloak)
#   keycloak.sh admin     create the first Keycloak administrator (Keycloak prompts for the password; stops it first)
#   keycloak.sh start     start it (idempotent)          keycloak.sh stop     stop it
#   keycloak.sh status    is it up, and where             keycloak.sh env      the lines for ~/.modeler-secrets.env
#   keycloak.sh migrate-db   move every realm, user and authenticator enrolment from the file database to PostgreSQL
#   keycloak.sh theme     copy in the product's sign-in pages (deploy/keycloak/themes/modeler-one); restart after
#   keycloak.sh connect [admin]   connect Modeler One's admin console to Keycloak, once (and again to rotate its
#                         secret): the service account, its roles, a new secret stored as the console's active key,
#                         the web's address and the login theme. Keycloak asks for its administrator's password.
#   keycloak.sh authenticator off|on [admin]   off: only modeler-admin needs an authenticator code (sign-in set-up
#                         and signing); everyone else uses their password alone. on: everyone again. TEMPORARY off
#                         (the owner, 2026-11-27) until the owner's end-to-end test. Same password prompt.
#
# Settings (environment, default in brackets):
#   MODELER_KEYCLOAK_HOST   the name or address browsers use for this server [this server's first address]
#   MODELER_KEYCLOAK_CERT, MODELER_KEYCLOAK_KEY   a PEM certificate and key to serve (e.g. from `tailscale cert`);
#                           unset: a self-signed certificate for MODELER_KEYCLOAK_HOST, made once by `install`
#   MODELER_KEYCLOAK_HOME   [~/modeler-keycloak]   MODELER_KEYCLOAK_HTTP_PORT [8080]   MODELER_KEYCLOAK_HTTPS_PORT [8443]
#   MODELER_KEYCLOAK_DB     [dev-file] or postgres: the `keycloak` database of deploy/server/postgres.sh, whose
#                           password file it reads (MODELER_POSTGRES_HOME, MODELER_POSTGRES_PORT as there)
#
# Browsers reach Keycloak only over HTTPS (it marks its cookies Secure, so plain HTTP sign-in fails off localhost).
# HTTP serves the local back channel: the API's key set (JWKS) and the web server's code exchange, on 127.0.0.1.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

KC_VERSION=26.7.5
# sha256 of keycloak-quarkus-dist-26.7.5.tar.gz from Maven Central (its published sha1 also checked on 2026-10-13).
KC_SHA256=87d680d13cf4600d232ca0433a2553c57ebf03e56f7718fc0d03a1a8705497c8
KC_URL="https://repo1.maven.org/maven2/org/keycloak/keycloak-quarkus-dist/$KC_VERSION/keycloak-quarkus-dist-$KC_VERSION.tar.gz"

KC_ROOT="${MODELER_KEYCLOAK_HOME:-$HOME/modeler-keycloak}"
KC_HOME="$KC_ROOT/keycloak-$KC_VERSION"
JDK="$KC_ROOT/jdk"
TLS="$KC_ROOT/tls"
HTTP_PORT="${MODELER_KEYCLOAK_HTTP_PORT:-8080}"
HTTPS_PORT="${MODELER_KEYCLOAK_HTTPS_PORT:-8443}"
HOST="${MODELER_KEYCLOAK_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
PUBLIC="https://$HOST:$HTTPS_PORT"
REALM_FILE="$REPO/deploy/keycloak/realm-modeler.json"
THEMES="$REPO/deploy/keycloak/themes"
PID_FILE="$LOGS/keycloak.pid"

die() { echo "keycloak.sh: $*" >&2; exit 1; }
java_major() { "$1" -version 2>&1 | awk -F'"' '/version/ {split($2, v, "."); print v[1]; exit}'; }

# The Java that runs Keycloak: ~/modeler-keycloak/jdk, or a Java 21+ already on PATH.
java_home() {
  if [ -x "$JDK/bin/java" ]; then echo "$JDK"; return; fi
  local j; j="$(command -v java || true)"
  if [ -n "$j" ] && [ "$(java_major "$j")" -ge 21 ] 2>/dev/null; then dirname "$(dirname "$(readlink -f "$j")")"; return; fi
  return 1
}

kc() {
  local home; home="$(java_home)" || die "no Java 21: run 'keycloak.sh install' first"
  JAVA_HOME="$home" PATH="$home/bin:$PATH" "$KC_HOME/bin/kc.sh" "$@"
}

# The TLS options Keycloak serves with (into TLS_OPTIONS): the person's own certificate, else the self-signed keystore.
tls_options() {
  if [ -n "${MODELER_KEYCLOAK_CERT:-}" ]; then
    [ -r "$MODELER_KEYCLOAK_CERT" ] && [ -r "${MODELER_KEYCLOAK_KEY:-}" ] || die "MODELER_KEYCLOAK_CERT / _KEY are not readable"
    TLS_OPTIONS=("--https-certificate-file=$MODELER_KEYCLOAK_CERT" "--https-certificate-key-file=$MODELER_KEYCLOAK_KEY")
  else
    [ -f "$TLS/keycloak.p12" ] || die "no certificate: run 'keycloak.sh install' (or set MODELER_KEYCLOAK_CERT and _KEY)"
    TLS_OPTIONS=("--https-key-store-file=$TLS/keycloak.p12")
  fi
}

# Keycloak's database options (into DB_OPTIONS): its embedded file database, or PostgreSQL with the password by
# environment (KC_DB_PASSWORD), never on the command line.
db_options() {
  if [ "${1:-${MODELER_KEYCLOAK_DB:-dev-file}}" = postgres ]; then
    local pass="${MODELER_POSTGRES_HOME:-$HOME/modeler-postgres}/secrets/keycloak.pass"
    [ -r "$pass" ] || die "MODELER_KEYCLOAK_DB=postgres but $pass is missing: run 'postgres.sh install' first"
    DB_OPTIONS=(--db=postgres "--db-url=jdbc:postgresql://127.0.0.1:${MODELER_POSTGRES_PORT:-5432}/keycloak" --db-username=keycloak)
    KC_DB_PASSWORD="$(cat "$pass")"
    export KC_DB_PASSWORD
  else
    DB_OPTIONS=(--db=dev-file)
  fi
}

running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

install_java() {
  if java_home >/dev/null; then echo "java: $(java_home)"; return; fi
  command -v conda >/dev/null || die "no Java 21 and no conda to install it (expected ~/miniforge3)"
  echo "installing Java 21 from conda-forge into $JDK"
  conda create -y -q -p "$JDK" -c conda-forge "openjdk=21" >/dev/null
  [ "$(java_major "$JDK/bin/java")" = 21 ] || die "conda installed no Java 21 in $JDK"
}

install_keycloak() {
  if [ -x "$KC_HOME/bin/kc.sh" ]; then echo "keycloak: $KC_HOME"; return; fi
  local tarball="$KC_ROOT/keycloak-$KC_VERSION.tar.gz"
  if [ ! -f "$tarball" ] || ! echo "$KC_SHA256  $tarball" | sha256sum -c --status; then
    echo "downloading Keycloak $KC_VERSION"
    curl -fsSL --retry 4 --retry-delay 15 -o "$tarball.part" "$KC_URL"
    mv "$tarball.part" "$tarball"
  fi
  echo "$KC_SHA256  $tarball" | sha256sum -c --status || die "checksum mismatch for $tarball: deleted, not used"
  tar -xzf "$tarball" -C "$KC_ROOT"
}

# A self-signed certificate for HOST (and localhost), made once. People trust tls/modeler-keycloak.crt on their
# devices; the keystore password is random and only in tls/keystore.pass (mode 600), never typed by anyone.
make_certificate() {
  [ -n "${MODELER_KEYCLOAK_CERT:-}" ] && { echo "certificate: $MODELER_KEYCLOAK_CERT"; return; }
  [ -f "$TLS/keycloak.p12" ] && { echo "certificate: $TLS/modeler-keycloak.crt"; return; }
  [ -n "$HOST" ] || die "set MODELER_KEYCLOAK_HOST to the name or address browsers use for this server"
  mkdir -p "$TLS" && chmod 700 "$TLS"
  ( umask 077; head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > "$TLS/keystore.pass" )
  local san="dns:localhost,ip:127.0.0.1"
  if [[ "$HOST" =~ ^[0-9.]+$ ]]; then san="ip:$HOST,$san"; else san="dns:$HOST,$san"; fi
  local home; home="$(java_home)"
  "$home/bin/keytool" -genkeypair -alias keycloak -keyalg RSA -keysize 3072 -validity 825 \
    -dname "CN=$HOST, O=Modeler One" -ext "SAN=$san" -storetype PKCS12 \
    -keystore "$TLS/keycloak.p12" -storepass:file "$TLS/keystore.pass" >/dev/null 2>&1
  "$home/bin/keytool" -exportcert -rfc -alias keycloak -keystore "$TLS/keycloak.p12" \
    -storepass:file "$TLS/keystore.pass" -file "$TLS/modeler-keycloak.crt" >/dev/null 2>&1
  echo "certificate: $TLS/modeler-keycloak.crt (self-signed for $HOST; trust it on each device that signs in)"
}

# The realm as imported: the file, with the web's own address (https://HOST:WEB_PORT, the MODELER_WEB_URL `env` prints)
# added to the web client's redirect URIs, so sign-in can return there with no change in the admin console. The file
# keeps only the fixed addresses (localhost, the LAN address); the server's name is known only here.
realm_for_host() {
  local out="$KC_ROOT/realm-import.json"
  python3 - "$REALM_FILE" "https://$HOST:$WEB_PORT/*" > "$out" <<'PY'
import json, sys
realm = json.load(open(sys.argv[1], encoding="utf-8"))
web = next(c for c in realm["clients"] if c["clientId"] == "modeler-web")
if sys.argv[2] not in web["redirectUris"]:
    web["redirectUris"].append(sys.argv[2])
json.dump(realm, sys.stdout, indent=1)
PY
  echo "$out"
}

# The product's own sign-in pages (deploy/keycloak/themes/modeler-one: Keycloak's keycloak.v2 pages with Modeler One's
# look and words), copied into Keycloak's themes folder, which Keycloak reads when it starts. The realm file names it as
# its login theme; a realm imported before it existed keeps Keycloak's pages until it is chosen once (`theme` says how).
install_theme() {
  [ -d "$KC_HOME/themes" ] || die "Keycloak is not installed: run 'keycloak.sh install'"
  rm -rf "$KC_HOME/themes/modeler-one"
  cp -R "$THEMES/modeler-one" "$KC_HOME/themes/modeler-one"
  echo "theme: modeler-one copied to $KC_HOME/themes"
}

cmd_theme() {
  install_theme
  echo "Next: 'keycloak.sh stop', then 'keycloak.sh start' (Keycloak reads its themes when it starts)."
  echo "Once, for a realm imported before 2026-11-24: Keycloak's admin console > realm 'modeler' > Realm settings >"
  echo "  Themes > Login theme: modeler-one > Save. The sign-in page then shows Modeler One's name and look."
}

cmd_install() {
  mkdir -p "$KC_ROOT"
  install_java
  install_keycloak
  install_theme
  make_certificate
  running && die "stop Keycloak before importing the realm ('keycloak.sh stop')"
  # --override false: a realm that already exists (its users, their TOTP) is kept, never replaced by the file.
  db_options
  kc import "${DB_OPTIONS[@]}" --file="$(realm_for_host)" --override=false
  echo "realm 'modeler': sign-in may return to https://$HOST:$WEB_PORT (if the realm existed already, add"
  echo "  https://$HOST:$WEB_PORT/* to Clients > modeler-web > Valid redirect URIs in the admin console)"
  echo "installed. Next: 'keycloak.sh admin' (first time only), then 'keycloak.sh start'"
}

cmd_admin() {
  running && cmd_stop
  echo "Create the first Keycloak administrator. Keycloak asks for the password; it is never stored by this script."
  db_options
  kc bootstrap-admin user "${DB_OPTIONS[@]}" --username="${1:-admin}"
}

cmd_start() {
  if running; then echo "keycloak already running: $PUBLIC"; return; fi
  [ -x "$KC_HOME/bin/kc.sh" ] || die "not installed: run 'keycloak.sh install'"
  local home; home="$(java_home)" || die "no Java 21: run 'keycloak.sh install' first"
  tls_options
  db_options
  local pass=""; [ -f "$TLS/keystore.pass" ] && pass="$(cat "$TLS/keystore.pass")"
  echo "starting Keycloak: $PUBLIC (back channel http://127.0.0.1:$HTTP_PORT)"
  # The keystore password goes by environment (KC_HTTPS_KEY_STORE_PASSWORD), so it never shows in the process list.
  KC_HTTPS_KEY_STORE_PASSWORD="$pass" JAVA_HOME="$home" PATH="$home/bin:$PATH" nohup "$KC_HOME/bin/kc.sh" start \
    "${DB_OPTIONS[@]}" --hostname="$PUBLIC" --hostname-backchannel-dynamic=true \
    --http-enabled=true --http-port="$HTTP_PORT" --https-port="$HTTPS_PORT" "${TLS_OPTIONS[@]}" \
    > "$LOGS/keycloak.log" 2>&1 &
  echo $! > "$PID_FILE"
  for _ in $(seq 1 60); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$HTTP_PORT/realms/modeler/.well-known/openid-configuration" 2>/dev/null; then
      echo "keycloak up: $PUBLIC/admin (administration), realm 'modeler'"; return
    fi
    running || die "Keycloak stopped while starting; see $LOGS/keycloak.log"
    sleep 3
  done
  die "Keycloak did not answer within 3 minutes; see $LOGS/keycloak.log"
}

# Every realm (master's administrators included), with its users and their credentials (password hashes, TOTP
# secrets), exported from the file database and imported into an empty PostgreSQL one. The export is written for this
# account only and deleted afterwards; the file database is left as it was, as the way back.
cmd_migrate_db() {
  [ "${MODELER_KEYCLOAK_DB:-}" = postgres ] || die "set MODELER_KEYCLOAK_DB=postgres (postgres.sh env prints it) first"
  running && cmd_stop
  local dir; dir="$KC_ROOT/migrate-$(date -u +%Y%m%dT%H%M%S)"
  ( umask 077; mkdir -p "$dir" )
  # shellcheck disable=SC2064 # the path is fixed now: the export is removed however this ends
  trap "rm -rf '$dir'" EXIT
  db_options dev-file
  kc export "${DB_OPTIONS[@]}" --dir="$dir" --users=realm_file
  db_options postgres
  kc import "${DB_OPTIONS[@]}" --dir="$dir" --override=false
  echo "Keycloak's realms, users and enrolments are in PostgreSQL. Start it: 'keycloak.sh start'"
}

# kcadm.sh, Keycloak's admin command line, with a session file of its own for this run only (it holds a token).
kca() {
  local home; home="$(java_home)" || die "no Java 21: run 'keycloak.sh install' first"
  local command=("$1"); shift
  [ "${command[0]}" = config ] && { command+=("$1"); shift; }      # `config credentials`: the option after both words
  JAVA_HOME="$home" PATH="$home/bin:$PATH" "$KC_HOME/bin/kcadm.sh" "${command[@]}" --config "$KCADM_CONFIG" "$@"
}

# A kcadm session for this run, as Keycloak's administrator `$1`: kcadm asks for the password itself.
kcadm_login() {
  KCADM_CONFIG="$(umask 077; mktemp "$KC_ROOT/kcadm-XXXXXX.config")"
  # shellcheck disable=SC2064 # the path is fixed now: the session file is removed however this ends
  trap "rm -f '$KCADM_CONFIG'" EXIT
  echo "Keycloak asks for the password of its administrator '$1' (realm master). It is used for this run only."
  kca config credentials --server "http://127.0.0.1:$HTTP_PORT" --realm master --user "$1"
}

# Who needs an authenticator code (the owner, 2026-11-27: "everywhere, except admins, for now only, after I test the
# full product end to end myself ... enable"). The signing step-up `modeler loa2 signing` asks for the password and the
# code. `off` sets its code step to DISABLED and adds a sub-flow that asks for the code only when the person holds
# modeler-admin (Condition - user role); it also clears the pending "set up your authenticator" of everyone else, which
# the console set at their creation. `on` restores the code step for everyone and disables the sub-flow; the console
# then asks new people to set one up again, and anyone without one sets it up the first time they sign. Sign-in itself
# (loa1) asks for the password only, either way. The API reads which holds from the flow (keycloak_admin).
LOA2_URL="authentication/flows/modeler%20loa2%20signing"
ADMIN_CODE="modeler loa2 admin code"
ADMIN_CODE_URL="authentication/flows/modeler%20loa2%20admin%20code"

# The id of a step of the signing flow: its provider (or, for a sub-flow, its name) at a level (0: the flow's own).
loa2_step() {
  kca get "$LOA2_URL/executions" -r modeler | python3 -c '
import json, sys
want, level = sys.argv[1], int(sys.argv[2])
for e in json.load(sys.stdin):
    if e.get("level") == level and (e.get("providerId") == want or (e.get("authenticationFlow") and e.get("displayName") == want)):
        print(e["id"])
        break' "$1" "$2"
}

require_step() {   # flow url, step id, REQUIRED | CONDITIONAL | DISABLED
  kca update "$1/executions" -r modeler --no-merge -b "{\"id\": \"$2\", \"requirement\": \"$3\"}"
}

cmd_authenticator() {
  local mode="${1:-}" user="${2:-admin}"
  [ "$mode" = off ] || [ "$mode" = on ] || die "say 'authenticator off' (only modeler-admin needs a code) or 'authenticator on'"
  [ -x "$KC_HOME/bin/kcadm.sh" ] || die "Keycloak is not installed on this machine ($(hostname -s 2>/dev/null || hostname)).
  Run this on the server, where Keycloak runs. From your own computer:
    ssh -t <the server> 'bash ~/Modeler_One_AI/deploy/server/keycloak.sh authenticator $mode'"
  running || die "Keycloak is not running: 'keycloak.sh start' first"
  kcadm_login "$user"
  local code sub
  code="$(loa2_step auth-otp-form 0)"
  [ -n "$code" ] || die "the signing flow 'modeler loa2 signing' has no authenticator step: is this the modeler realm?"
  sub="$(loa2_step "$ADMIN_CODE" 0)"
  if [ "$mode" = off ]; then
    if [ -z "$sub" ]; then
      kca create "$LOA2_URL/executions/flow" -r modeler -s "alias=$ADMIN_CODE" -s type=basic-flow \
        -s provider=registration-page-form -s "description=The authenticator code, for modeler-admin only (keycloak.sh authenticator off)"
      kca create "$ADMIN_CODE_URL/executions/execution" -r modeler -s provider=conditional-user-role
      kca create "$ADMIN_CODE_URL/executions/execution" -r modeler -s provider=auth-otp-form
      sub="$(loa2_step "$ADMIN_CODE" 0)"
      local role otp
      role="$(loa2_step conditional-user-role 1)"
      otp="$(loa2_step auth-otp-form 1)"
      kca create "authentication/executions/$role/config" -r modeler \
        -b '{"alias": "modeler admins only", "config": {"condUserRole": "modeler-admin", "negate": "false"}}'
      require_step "$ADMIN_CODE_URL" "$role" REQUIRED
      require_step "$ADMIN_CODE_URL" "$otp" REQUIRED
    fi
    require_step "$LOA2_URL" "$sub" CONDITIONAL
    require_step "$LOA2_URL" "$code" DISABLED
    echo "signing: the password for everyone; the authenticator code for modeler-admin only"
    # nobody but an administrator is asked to set one up at sign-in any more
    local admins
    admins="$(kca get roles/modeler-admin/users -r modeler --fields id --format csv --noquotes | tr '\n' ' ')"
    kca get users -r modeler -q max=5000 --fields id,username,requiredActions | python3 -c '
import json, sys
admins = set(sys.argv[1].split())
for u in json.load(sys.stdin):
    pending = u.get("requiredActions") or []
    if "CONFIGURE_TOTP" in pending and u["id"] not in admins:
        print(u["id"], u.get("username", ""), json.dumps([a for a in pending if a != "CONFIGURE_TOTP"]).replace(" ", ""))' "$admins" \
      | while read -r id name rest; do
          kca update "users/$id" -r modeler -s "requiredActions=$rest"
          echo "  $name: no longer asked to set up an authenticator"
        done
    echo "authenticator OFF except for modeler-admin. TEMPORARY: 'keycloak.sh authenticator on' turns it back on."
  else
    require_step "$LOA2_URL" "$code" REQUIRED
    [ -n "$sub" ] && require_step "$LOA2_URL" "$sub" DISABLED
    echo "authenticator ON for everyone: signing asks for the password and the code; a person without an authenticator"
    echo "  sets one up the first time they sign, and the console asks new people to set one up at their first sign-in."
  fi
}

# Modeler One's admin console reaches Keycloak as the service account `modeler-admin-api` (deploy/keycloak/README.md).
# This does, once, every step that was done by hand in Keycloak's admin console (the owner, 2026-11-27): the client
# (made, or repaired to service-account only), its service account's realm-management roles, the web's address among the
# sign-in redirects, the product's login theme, and a NEW client secret (an older one stops working). The secret goes
# by pipe to modeler_api.keycloak_connect, which tests it and stores it, sealed, as the console's active key, audited.
# The only password is Keycloak's administrator's, typed into kcadm's own prompt; nothing here keeps it.
cmd_connect() {
  local user="${1:-admin}"
  # the server's own Keycloak, not a laptop's checkout: say where to run it before anything else
  [ -x "$KC_HOME/bin/kcadm.sh" ] || die "Keycloak is not installed on this machine ($(hostname -s 2>/dev/null || hostname)).
  Run this on the server, where Keycloak runs. From your own computer:
    ssh -t <the server> 'bash ~/Modeler_One_AI/deploy/server/keycloak.sh connect'"
  running || die "Keycloak is not running: 'keycloak.sh start' first"
  [ -n "${MODELER_OIDC_ISSUER:-}" ] || die "Modeler One does not sign in through Keycloak yet: add the lines of 'keycloak.sh env' to $SECRETS_FILE and restart it"
  [ -n "${MODELER_MASTER_KEY:-}" ] || die "MODELER_MASTER_KEY is not set in $SECRETS_FILE: the console seals its keys with it"
  kcadm_login "$user"

  local id
  id="$(kca get clients -r modeler -q clientId=modeler-admin-api --fields id --format csv --noquotes)"
  if [ -z "$id" ]; then
    id="$(kca create clients -r modeler -i -s clientId=modeler-admin-api -s enabled=true -s publicClient=false \
      -s serviceAccountsEnabled=true -s standardFlowEnabled=false -s implicitFlowEnabled=false \
      -s directAccessGrantsEnabled=false -s clientAuthenticatorType=client-secret \
      -s "description=The admin console's people and companies (keycloak.sh connect)")"
    echo "client modeler-admin-api: created"
  else
    kca update "clients/$id" -r modeler -s enabled=true -s publicClient=false -s serviceAccountsEnabled=true \
      -s standardFlowEnabled=false -s implicitFlowEnabled=false -s directAccessGrantsEnabled=false
    echo "client modeler-admin-api: there, kept to its service account only"
  fi
  kca add-roles -r modeler --uusername service-account-modeler-admin-api --cclientid realm-management \
    --rolename manage-users --rolename query-users --rolename view-realm --rolename view-users
  echo "its service account: realm-management manage-users, query-users, view-realm, view-users"

  local web="${MODELER_WEB_URL:-https://$HOST:$WEB_PORT}" wid uris
  wid="$(kca get clients -r modeler -q clientId=modeler-web --fields id --format csv --noquotes)"
  if [ -n "$wid" ]; then
    uris="$(kca get "clients/$wid" -r modeler --fields redirectUris | python3 -c '
import json, sys
uris = json.load(sys.stdin).get("redirectUris") or []
want = sys.argv[1].rstrip("/") + "/*"
print(json.dumps(uris + [want]) if want not in uris else "")' "$web")"
    if [ -n "$uris" ]; then kca update "clients/$wid" -r modeler -s "redirectUris=$uris"; echo "sign-in may return to $web"; fi
  fi
  if [ -d "$KC_HOME/themes/modeler-one" ]; then
    kca update realms/modeler -s loginTheme=modeler-one && echo "login theme: modeler-one"
  fi

  kca create "clients/$id/client-secret" -r modeler >/dev/null
  echo "a new client secret is made; storing it in the console"
  kca get "clients/$id/client-secret" -r modeler \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["value"], end="")' \
    | (cd "$REPO" && uv run --quiet python -m modeler_api.keycloak_connect --by "keycloak:$user via keycloak.sh connect on $(hostname)") \
    || die "the console could not keep the new secret (above). The old one no longer works: fix that, then run 'keycloak.sh connect' again"
}

cmd_stop() {
  if ! running; then echo "keycloak not running"; rm -f "$PID_FILE"; return; fi
  local pid; pid="$(cat "$PID_FILE")"
  pkill -TERM -P "$pid" 2>/dev/null || true; kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
  rm -f "$PID_FILE"; echo "keycloak stopped"
}

cmd_status() {
  if running && curl -fsS -o /dev/null "http://127.0.0.1:$HTTP_PORT/realms/modeler/.well-known/openid-configuration" 2>/dev/null; then
    echo "keycloak UP    $PUBLIC/admin   realm modeler   (log $LOGS/keycloak.log)"
  else
    echo "keycloak DOWN  (start: bash deploy/server/keycloak.sh start)"; return 1
  fi
}

cmd_env() {
  cat <<EOF
# Keycloak sign-in (deploy/server/keycloak.sh env): add to ~/.modeler-secrets.env, then restart the stack.
export MODELER_OIDC_ISSUER=$PUBLIC/realms/modeler
export MODELER_OIDC_JWKS_URL=http://127.0.0.1:$HTTP_PORT/realms/modeler/protocol/openid-connect/certs
export MODELER_OIDC_BACKCHANNEL=http://127.0.0.1:$HTTP_PORT/realms/modeler
# the web over HTTPS with the same certificate (apps/web/server.mjs), so its sign-in cookies are Secure
export MODELER_WEB_URL=https://$HOST:$WEB_PORT
EOF
  if [ -n "${MODELER_KEYCLOAK_CERT:-}" ]; then
    echo "export MODELER_WEB_TLS_CERT=$MODELER_KEYCLOAK_CERT"
    echo "export MODELER_WEB_TLS_KEY=$MODELER_KEYCLOAK_KEY"
  else
    echo "export MODELER_WEB_TLS_PFX=$TLS/keycloak.p12"
    echo "export MODELER_WEB_TLS_PFX_PASSFILE=$TLS/keystore.pass"
  fi
}

case "${1:-}" in
  install) cmd_install ;;
  admin) shift; cmd_admin "$@" ;;
  start) cmd_start ;;
  stop) cmd_stop ;;
  status) cmd_status ;;
  env) cmd_env ;;
  migrate-db) cmd_migrate_db ;;
  theme) cmd_theme ;;
  connect) shift; cmd_connect "$@" ;;
  authenticator) shift; cmd_authenticator "$@" ;;
  *) sed -n '2,25p' "$0"; exit 2 ;;
esac
