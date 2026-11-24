// Where signing out ends (app/auth/logout returns here from Keycloak): says the session ended here and at the sign-in
// page, instead of landing on a sign-in form as if nothing had happened.

import Link from "next/link";

import { AuthPage } from "@/components/auth/AuthPage";
import { oidcConfig } from "@/lib/oidc";

export const metadata = { title: "Signed out · Modeler One" };

export default function SignedOut() {
  const oidc = oidcConfig();
  return (
    <AuthPage title="You have signed out" testId="signed-out-page">
      <p>Your Modeler One session and your session at the sign-in page have both ended.</p>
      <p className="muted">On a shared computer, close the browser too.</p>
      {oidc
        ? <a className="btn primary auth-go" href="/auth/login" data-testid="signed-out-again">Sign in again</a>
        : <Link className="btn primary auth-go" href="/" data-testid="signed-out-again">Back to Modeler One</Link>}
    </AuthPage>
  );
}
