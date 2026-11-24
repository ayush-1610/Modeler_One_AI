import { NextResponse, type NextRequest } from "next/server";

import { identityToken } from "@/lib/api";
import {
  ACCESS_ROLES, clearTokens, COOKIE, oidcConfig, PUBLIC_PAGES, realmRoles, secondsLeft, SHELL_HEADER, storeTokens,
  type TokenSet,
} from "@/lib/oidc";

// Every request but the sign-in route handlers and the build's files passes here (Next 16's proxy, formerly middleware):
// - the sign-in pages (/signin, /signed-out) and /no-access are drawn without the app's sidebar (SHELL_HEADER);
// With Keycloak sign-in on (lib/oidc.ts):
// - an access token about to expire is refreshed over the back channel, and the new cookies go to the browser and, for
//   this request, to the server components (they read the overridden cookie header);
// - an API call (/api/*, rewritten to the backend in next.config.mjs) carries the person's own access token, whatever
//   the browser's code sent;
// - without a session, a page goes to the product's sign-in page (/signin, the owner 2026-11-24: "we need to work in
//   login page"), or straight back to Keycloak when a session has just ended (Keycloak may still know the person, so
//   no password is asked); an API call answers 401;
// - a person signed in with no Modeler One role sees /no-access, not pages that would each refuse.
// Without Keycloak (the DEV sign-in) only the sidebar rule applies.
export async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  const headers = new Headers(request.headers);
  headers.delete(SHELL_HEADER);                                     // set here only, never by the browser
  const bare = PUBLIC_PAGES.test(path) || path === "/no-access";
  if (bare) headers.set(SHELL_HEADER, "none");
  const oidc = oidcConfig();
  if (!oidc || PUBLIC_PAGES.test(path)) return NextResponse.next({ request: { headers } });

  const isApi = path.startsWith("/api/");
  let access = request.cookies.get(COOKIE.access)?.value;
  const refresh = request.cookies.get(COOKIE.refresh)?.value;
  let refreshed: TokenSet | null = null;
  if (refresh && secondsLeft(access) < 30) {
    refreshed = await identityToken(oidc, { grant_type: "refresh_token", refresh_token: refresh });
    if (refreshed) access = refreshed.access_token;
  }
  if (!access || secondsLeft(access) <= 0) {
    const back = encodeURIComponent(path + request.nextUrl.search);
    const hadSession = Boolean(refresh || request.cookies.get(COOKIE.access)?.value);
    const out = isApi
      ? NextResponse.json({ detail: "Your session has ended: sign in again." }, { status: 401 })
      : NextResponse.redirect(new URL(hadSession ? `/auth/login?return=${back}` : `/signin?return=${back}`, oidc.webUrl));
    clearTokens(out.cookies, oidc);
    return out;
  }
  if (!isApi && path !== "/no-access" && !realmRoles(access).some((r) => (ACCESS_ROLES as readonly string[]).includes(r))) {
    return NextResponse.redirect(new URL("/no-access", oidc.webUrl));
  }
  if (isApi) headers.set("authorization", `Bearer ${access}`);
  if (refreshed) {
    const jar = new Map(request.cookies.getAll().map((c) => [c.name, c.value]));
    jar.set(COOKIE.access, refreshed.access_token);
    if (refreshed.refresh_token) jar.set(COOKIE.refresh, refreshed.refresh_token);
    if (refreshed.id_token) jar.set(COOKIE.id, refreshed.id_token);
    headers.set("cookie", [...jar].map(([name, value]) => `${name}=${value}`).join("; "));
  }
  const response = NextResponse.next({ request: { headers } });
  if (refreshed) storeTokens(response.cookies, oidc, refreshed, request.cookies.get(COOKIE.id)?.value);
  return response;
}

export const config = {
  // the route handlers sign in themselves; the build's files and the icon load on the sign-in page too
  matcher: ["/((?!auth/|_next/|favicon\\.ico|icon\\.svg).*)"],
};
