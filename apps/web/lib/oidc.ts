// Sign-in through Keycloak (T-06, D10), for the web server only: the Authorization Code flow with PKCE, the tokens in
// httpOnly cookies the browser's code never reads. The proxy (proxy.ts) adds the person's access token to every API
// call and refreshes it; the routes under app/auth sign in, step up for a signature, and sign out.
//
// Sign-in is on when MODELER_OIDC_ISSUER is set (deploy/server/keycloak.sh env prints the values):
//   MODELER_OIDC_ISSUER       the realm's public address, where browsers sign in (https://<server>:8443/realms/modeler)
//   MODELER_OIDC_BACKCHANNEL  where this server exchanges codes and refreshes tokens (default: the issuer)
//   MODELER_OIDC_CLIENT_ID    [modeler-web]
//   MODELER_WEB_URL           this web app's address as people open it; the sign-in returns to <it>/auth/callback
// Unset, the web runs as before with the DEV sign-in (MODELER_DEV_AUTH on the API), which is never Part 11.
// Web Crypto only, so the same code runs in the proxy and in the route handlers; the token endpoint is called
// through the one client (lib/api.ts `identityToken`).

export type OidcConfig = { issuer: string; backchannel: string; clientId: string; webUrl: string; secure: boolean };

export type TokenSet = {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  refresh_expires_in?: number;
};

const trim = (url: string) => url.replace(/\/+$/, "");

export function oidcConfig(): OidcConfig | null {
  const issuer = process.env.MODELER_OIDC_ISSUER;
  if (!issuer) return null;
  const webUrl = process.env.MODELER_WEB_URL;
  if (!webUrl) {
    throw new Error("MODELER_OIDC_ISSUER is set but MODELER_WEB_URL is not: sign-in must return to the web's own address");
  }
  return {
    issuer: trim(issuer),
    backchannel: trim(process.env.MODELER_OIDC_BACKCHANNEL || issuer),
    clientId: process.env.MODELER_OIDC_CLIENT_ID || "modeler-web",
    webUrl: trim(webUrl),
    secure: webUrl.startsWith("https://"),
  };
}

export const COOKIE = { access: "modeler_at", refresh: "modeler_rt", id: "modeler_idt", request: "modeler_auth_req" } as const;

/** httpOnly, same-site, and Secure whenever the web is served over HTTPS. */
export function cookieOptions(config: OidcConfig, maxAge: number) {
  return { httpOnly: true, sameSite: "lax" as const, secure: config.secure, path: "/", maxAge };
}

const b64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

export function randomToken(bytes = 32): string {
  return b64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

/** The PKCE S256 challenge of a verifier. */
export async function pkceChallenge(verifier: string): Promise<string> {
  return b64url(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier))));
}

/** A JWT's claims, read without checking its signature: the API verifies every token it is given (JWKS, issuer,
 *  audience). The web reads only the expiry and the person's name. */
export function claims(jwt: string | undefined): Record<string, unknown> | null {
  const part = jwt?.split(".")[1];
  if (!part) return null;
  try {
    const padded = part.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (part.length % 4)) % 4);
    return JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(padded), (c) => c.charCodeAt(0))));
  } catch {
    return null;
  }
}

/** Seconds until a token expires (negative when it has; -Infinity when it cannot be read). */
export function secondsLeft(jwt: string | undefined): number {
  const exp = claims(jwt)?.exp;
  return typeof exp === "number" ? exp - Date.now() / 1000 : -Infinity;
}

/** Where to go after signing in: a path on this site only, never another site (no open redirect). */
export function safeReturn(path: string | null | undefined): string {
  return path && path.startsWith("/") && !path.startsWith("//") && !path.startsWith("/\\") ? path : "/";
}

type CookieJar = {
  set: (name: string, value: string, options: ReturnType<typeof cookieOptions>) => unknown;
};

/** Keep a token set for as long as Keycloak keeps the session (its refresh token's lifetime). */
export function storeTokens(jar: CookieJar, config: OidcConfig, tokens: TokenSet, previousIdToken?: string) {
  const maxAge = tokens.refresh_expires_in && tokens.refresh_expires_in > 0 ? tokens.refresh_expires_in : 1800;
  jar.set(COOKIE.access, tokens.access_token, cookieOptions(config, maxAge));
  if (tokens.refresh_token) jar.set(COOKIE.refresh, tokens.refresh_token, cookieOptions(config, maxAge));
  const idToken = tokens.id_token ?? previousIdToken;
  if (idToken) jar.set(COOKIE.id, idToken, cookieOptions(config, maxAge));
}

export function clearTokens(jar: CookieJar, config: OidcConfig) {
  for (const name of [COOKIE.access, COOKIE.refresh, COOKIE.id, COOKIE.request]) jar.set(name, "", cookieOptions(config, 0));
}
