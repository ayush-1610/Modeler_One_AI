import { NextResponse, type NextRequest } from "next/server";

import { clearTokens, COOKIE, oidcConfig } from "@/lib/oidc";

// Sign out here and at Keycloak (its session ends too), then come back to the web's start page.
export async function GET(request: NextRequest) {
  const config = oidcConfig();
  if (!config) return NextResponse.redirect(new URL("/", request.url));
  const end = new URL(`${config.issuer}/protocol/openid-connect/logout`);
  end.search = new URLSearchParams({
    client_id: config.clientId, post_logout_redirect_uri: `${config.webUrl}/`,
    ...(request.cookies.get(COOKIE.id)?.value ? { id_token_hint: request.cookies.get(COOKIE.id)!.value } : {}),
  }).toString();
  const response = NextResponse.redirect(end);
  clearTokens(response.cookies, config);
  return response;
}
