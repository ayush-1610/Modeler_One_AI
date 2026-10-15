// Server-only reads of the sign-in (the layout imports it): the browser's code never sees the session cookies.

import { cookies } from "next/headers";

import { claims, COOKIE, oidcConfig } from "@/lib/oidc";

/** The signed-in person's name, from the ID token (null with the DEV sign-in). Reading the cookies first keeps every
 *  page rendered per request, so a page built without Keycloak still shows who is signed in once it is configured. */
export async function signedInName(): Promise<string | null> {
  const jar = await cookies();
  if (!oidcConfig()) return null;
  const id = claims(jar.get(COOKIE.id)?.value);
  const name = id?.name ?? id?.preferred_username;
  return typeof name === "string" ? name : null;
}
