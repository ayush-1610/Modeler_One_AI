import { NextResponse, type NextRequest } from "next/server";

import { identityToken } from "@/lib/api";
import { clearTokens, COOKIE, oidcConfig, secondsLeft, storeTokens, type TokenSet } from "@/lib/oidc";

// With Keycloak sign-in on (lib/oidc.ts), every request but the sign-in routes passes here (Next 16's proxy, formerly
// middleware):
// - an access token about to expire is refreshed over the back channel, and the new cookies go to the browser and, for
//   this request, to the server components (they read the overridden cookie header);
// - an API call (/api/*, rewritten to the backend in next.config.mjs) carries the person's own access token, whatever
//   the browser's code sent;
// - without a session a page goes to the sign-in, and an API call answers 401.
// Without Keycloak (the DEV sign-in) it changes nothing.
export async function proxy(request: NextRequest) {
  const oidc = oidcConfig();
  if (!oidc) return NextResponse.next();
  const isApi = request.nextUrl.pathname.startsWith("/api/");
  let access = request.cookies.get(COOKIE.access)?.value;
  const refresh = request.cookies.get(COOKIE.refresh)?.value;
  let refreshed: TokenSet | null = null;
  if (refresh && secondsLeft(access) < 30) {
    refreshed = await identityToken(oidc, { grant_type: "refresh_token", refresh_token: refresh });
    if (refreshed) access = refreshed.access_token;
  }
  if (!access || secondsLeft(access) <= 0) {
    const out = isApi
      ? NextResponse.json({ detail: "Your session has ended: sign in again." }, { status: 401 })
      : NextResponse.redirect(new URL(
          `/auth/login?return=${encodeURIComponent(request.nextUrl.pathname + request.nextUrl.search)}`, oidc.webUrl));
    clearTokens(out.cookies, oidc);
    return out;
  }
  const headers = new Headers(request.headers);
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
  matcher: ["/((?!auth/|_next/|favicon\\.ico).*)"],
};
