// Where signing out ends (app/auth/logout returns here from Keycloak, the address the realm allows): the sign-in page
// itself, with a note that the session ended here and at the sign-in page (the owner, 2026-11-27: "signed out lands back
// to sign in page"), so the next step is one button away.

import Link from "next/link";

import { AuthPage, Where } from "@/components/auth/AuthPage";
import { oidcConfig } from "@/lib/oidc";

export const metadata = { title: "Signed out · Modeler One" };

export default function SignedOut() {
  const oidc = oidcConfig();
  return (
    <AuthPage title="Login" lede={<>You have signed out. Please sign in again <Where />.</>} testId="signed-out-page">
      <div className="banner ok" role="status" data-testid="signed-out-note">
        <strong>You have signed out.</strong> Your Modeler One session and your session at the sign-in page have both ended.
        On a shared computer, close the browser too.
      </div>
      {oidc
        ? <a className="btn primary auth-go" href="/auth/login" data-testid="signed-out-again">Lets Go →</a>
        : <Link className="btn primary auth-go" href="/" data-testid="signed-out-again">Lets Go →</Link>}
    </AuthPage>
  );
}
