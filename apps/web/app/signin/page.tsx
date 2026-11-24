// The product's sign-in page (the owner, 2026-11-24: "we need to work in login page"): where someone who is not signed
// in lands, and where a sign-in that did not complete says why. The password and the authenticator code are typed at
// Keycloak (its Modeler One pages, deploy/keycloak/themes/modeler-one), never here (21 CFR Part 11; CLAUDE.md).

import { cookies } from "next/headers";
import Link from "next/link";
import { redirect } from "next/navigation";

import { AuthPage } from "@/components/auth/AuthPage";
import { COOKIE, oidcConfig, safeReturn, secondsLeft } from "@/lib/oidc";

export const metadata = { title: "Sign in · Modeler One" };

export default async function SignIn({ searchParams }: { searchParams: Promise<{ return?: string; problem?: string }> }) {
  const { return: ret, problem } = await searchParams;
  const back = safeReturn(ret);
  const oidc = oidcConfig();
  if (!oidc) {
    return (
      <AuthPage title="Development sign-in" testId="signin-page">
        <p>This server signs everyone in as one development user, with no password.</p>
        <div className="banner warn" data-testid="signin-dev">
          For testing with made-up data only: it is not a Part 11 sign-in, and it names no one in the records.
        </div>
        <Link className="btn primary auth-go" href={back} data-testid="signin-go">Continue</Link>
      </AuthPage>
    );
  }
  if (!problem && secondsLeft((await cookies()).get(COOKIE.access)?.value) > 0) redirect(back);   // already signed in
  return (
    <AuthPage title="Sign in to Modeler One" testId="signin-page">
      {problem && (
        <div className="banner err" role="alert" data-testid="signin-problem">
          Sign-in did not complete: {problem}. Try again; if it keeps happening, tell your administrator.
        </div>
      )}
      <p>Sign in with your company account.</p>
      <a className="btn primary auth-go" href={`/auth/login?return=${encodeURIComponent(back)}`} data-testid="signin-go">Sign in</a>
      <ul className="auth-notes">
        <li>Your password and authenticator code are typed on your company&apos;s sign-in page, never into Modeler One.</li>
        <li>Each electronic signature asks for them again (21 CFR Part 11).</li>
        <li>Forgot your password or lost your authenticator? Ask your Modeler One administrator to reset it.</li>
      </ul>
    </AuthPage>
  );
}
