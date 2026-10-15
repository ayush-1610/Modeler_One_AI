import { NextResponse, type NextRequest } from "next/server";

import { COOKIE, cookieOptions, oidcConfig, pkceChallenge, randomToken, safeReturn } from "@/lib/oidc";

// Start a sign-in at Keycloak (lib/oidc.ts). `?return=` is where to come back to; `?step_up=1` asks for the signing
// level (acr loa2): Keycloak asks for the password and the authenticator code again, as every electronic signature
// needs (21 CFR 11.200). `?popup=1` is the step-up window the signing dialog opens, so the page keeps its state.
export async function GET(request: NextRequest) {
  const config = oidcConfig();
  if (!config) return NextResponse.redirect(new URL("/", request.url));
  const query = request.nextUrl.searchParams;
  const stepUp = query.get("step_up") === "1";
  const pending = {
    state: randomToken(), nonce: randomToken(), verifier: randomToken(48),
    ret: safeReturn(query.get("return")), popup: query.get("popup") === "1",
  };
  const authorize = new URL(`${config.issuer}/protocol/openid-connect/auth`);
  authorize.search = new URLSearchParams({
    client_id: config.clientId, response_type: "code", scope: "openid",
    redirect_uri: `${config.webUrl}/auth/callback`, state: pending.state, nonce: pending.nonce,
    code_challenge: await pkceChallenge(pending.verifier), code_challenge_method: "S256",
    ...(stepUp ? { acr_values: "loa2" } : {}),
  }).toString();
  const response = NextResponse.redirect(authorize);
  response.cookies.set(COOKIE.request, JSON.stringify(pending), cookieOptions(config, 600));
  return response;
}
