import { NextResponse, type NextRequest } from "next/server";

import { identityToken } from "@/lib/api";
import { claims, COOKIE, cookieOptions, oidcConfig, safeReturn, storeTokens } from "@/lib/oidc";

type Pending = { state: string; nonce: string; verifier: string; ret: string; popup: boolean };

function problem(message: string, status = 400) {
  const body = `<!doctype html><meta charset="utf-8"><title>Sign-in did not complete</title>
<p>Sign-in did not complete: ${message.replace(/[<&>]/g, "")}</p><p><a href="/auth/login">Sign in again</a></p>`;
  return new NextResponse(body, { status, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

// Keycloak returns here with a code. The code is exchanged over the back channel with the PKCE verifier; the state
// and the ID token's nonce, issuer and audience must match the request this browser started.
export async function GET(request: NextRequest) {
  const config = oidcConfig();
  if (!config) return NextResponse.redirect(new URL("/", request.url));
  const query = request.nextUrl.searchParams;
  let pending: Pending;
  try {
    pending = JSON.parse(request.cookies.get(COOKIE.request)?.value ?? "") as Pending;
  } catch {
    return problem("the sign-in request has expired or was started in another browser");
  }
  if (query.get("error")) return problem(query.get("error_description") || query.get("error") || "refused by Keycloak");
  if (!pending.state || query.get("state") !== pending.state) return problem("the answer does not belong to this sign-in");
  const tokens = await identityToken(config, {
    grant_type: "authorization_code", code: query.get("code") ?? "", code_verifier: pending.verifier,
    redirect_uri: `${config.webUrl}/auth/callback`,
  });
  if (!tokens) return problem("Keycloak did not issue tokens for this code", 502);
  const id = claims(tokens.id_token);
  const audience = id?.aud;
  if (!id || id.nonce !== pending.nonce || id.iss !== config.issuer ||
      !(audience === config.clientId || (Array.isArray(audience) && audience.includes(config.clientId)))) {
    return problem("the ID token does not match this sign-in");
  }
  const response = pending.popup
    ? new NextResponse(
        `<!doctype html><meta charset="utf-8"><title>Identity confirmed</title><p>Identity confirmed. This window closes.</p>
<script>if (window.opener) { window.opener.postMessage({ type: "modeler:stepped-up" }, window.location.origin); window.close(); }</script>`,
        { headers: { "Content-Type": "text/html; charset=utf-8" } })
    : NextResponse.redirect(`${config.webUrl}${safeReturn(pending.ret)}`);
  storeTokens(response.cookies, config, tokens);
  response.cookies.set(COOKIE.request, "", cookieOptions(config, 0));
  return response;
}
