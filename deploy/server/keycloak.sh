#!/usr/bin/env bash
# Keycloak for the single-node deployment (T-06 / D10): sign-in, and the step-up every electronic signature asks for.
# No sudo: Java 21 comes from conda-forge (this server's ~/miniforge3) and Keycloak from Maven Central, both under
# ~/modeler-keycloak. Passwords are typed only into Keycloak's own prompts and pages; this script never asks for one.
#
#   keycloak.sh install   Java 21 + Keycloak (checksum checked), a TLS certificate, the realm (deploy/keycloak)
#   keycloak.sh admin     create the first Keycloak administrator (Keycloak prompts for the password; stops it first)
#   keycloak.sh start     start it (idempotent)          keycloak.sh stop     stop it
#   keycloak.sh status    is it up, and where             keycloak.sh env      the lines for ~/.modeler-secrets.env
#
# Settings (environment, default in brackets):
#   MODELER_KEYCLOAK_HOST   the name or address browsers use for this server [this server's first address]
#   MODELER_KEYCLOAK_CERT, MODELER_KEYCLOAK_KEY   a PEM certificate and key to serve (e.g. from `tailscale cert`);
#                           unset: a self-signed certificate for MODELER_KEYCLOAK_HOST, made once by `install`
#   MODELER_KEYCLOAK_HOME   [~/modeler-keycloak]   MODELER_KEYCLOAK_HTTP_PORT [8080]   MODELER_KEYCLOAK_HTTPS_PORT [8443]
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

cmd_install() {
  mkdir -p "$KC_ROOT"
  install_java
  install_keycloak
  make_certificate
  running && die "stop Keycloak before importing the realm ('keycloak.sh stop')"
  # --override false: a realm that already exists (its users, their TOTP) is kept, never replaced by the file.
  kc import --db=dev-file --file="$REALM_FILE" --override=false
  echo "installed. Next: 'keycloak.sh admin' (first time only), then 'keycloak.sh start'"
}

cmd_admin() {
  running && cmd_stop
  echo "Create the first Keycloak administrator. Keycloak asks for the password; it is never stored by this script."
  kc bootstrap-admin user --db=dev-file --username="${1:-admin}"
}

cmd_start() {
  if running; then echo "keycloak already running: $PUBLIC"; return; fi
  [ -x "$KC_HOME/bin/kc.sh" ] || die "not installed: run 'keycloak.sh install'"
  local home; home="$(java_home)" || die "no Java 21: run 'keycloak.sh install' first"
  tls_options
  local pass=""; [ -f "$TLS/keystore.pass" ] && pass="$(cat "$TLS/keystore.pass")"
  echo "starting Keycloak: $PUBLIC (back channel http://127.0.0.1:$HTTP_PORT)"
  # The keystore password goes by environment (KC_HTTPS_KEY_STORE_PASSWORD), so it never shows in the process list.
  KC_HTTPS_KEY_STORE_PASSWORD="$pass" JAVA_HOME="$home" PATH="$home/bin:$PATH" nohup "$KC_HOME/bin/kc.sh" start \
    --db=dev-file --hostname="$PUBLIC" --hostname-backchannel-dynamic=true \
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
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
