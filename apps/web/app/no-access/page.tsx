// A person signed in through Keycloak whose account has no Modeler One role yet (proxy.ts sends them here): one page
// that says so and what to ask for, instead of every page answering "forbidden".

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AuthPage } from "@/components/auth/AuthPage";
import { COOKIE, oidcConfig, realmRoles } from "@/lib/oidc";
import { signedInName } from "@/lib/session";

export const metadata = { title: "No access yet · Modeler One" };

export default async function NoAccess() {
  if (!oidcConfig()) redirect("/");                       // the DEV sign-in has every role
  const name = await signedInName();
  const roles = realmRoles((await cookies()).get(COOKIE.access)?.value).filter((r) => r.startsWith("modeler-"));
  return (
    <AuthPage title="Your account has no access yet" lede="You are signed in; your administrator opens Modeler One to you." testId="no-access-page">
      <p>
        You are signed in{name ? <> as <strong>{name}</strong></> : null}, but your account has no Modeler One role
        {roles.includes("modeler-qa") ? " that opens projects (the QA role opens none yet)" : ""}.
      </p>
      <p>Ask your administrator to give you one in Admin → People:</p>
      <ul className="auth-notes">
        <li><strong>Viewer</strong>: reads the projects shared with you.</li>
        <li><strong>Curator</strong>: creates projects and changes your own.</li>
        <li><strong>Reviewer</strong>: as a curator, and signs the projects shared with you.</li>
      </ul>
      <div className="auth-acts">
        <a className="btn primary" href="/" data-testid="no-access-again">Try again</a>
        <a className="btn" href="/auth/logout" data-testid="no-access-sign-out">Sign out</a>
      </div>
    </AuthPage>
  );
}
