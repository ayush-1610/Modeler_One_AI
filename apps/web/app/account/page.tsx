// The signed-in person's own page (the owner, 2026-11-24: the pages the way in was missing): who they are to Modeler
// One, what their roles let them do, their session, and where they change their password or authenticator (at
// Keycloak's account page, never here) or sign out.

import { cookies } from "next/headers";

import { Hero } from "@/components/kit";
import { ApiProblem } from "@/components/ui";
import { serverGet } from "@/lib/api";
import { claims, COOKIE, oidcConfig } from "@/lib/oidc";

export const metadata = { title: "Your account · Modeler One" };

const ROLES: Record<string, string> = {
  "modeler-viewer": "Viewer: reads the projects shared with you",
  "modeler-curator": "Curator: creates projects and changes your own",
  "modeler-reviewer": "Reviewer: signs the projects shared with you (MAP, records, escalation decisions)",
  "modeler-qa": "QA: no project access yet",
  "modeler-admin": "Administrator: the admin console (people, companies, keys, models, limits)",
};

const when = (seconds: unknown) =>
  typeof seconds === "number" ? new Date(seconds * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC" : "—";

export default async function AccountPage() {
  const oidc = oidcConfig();
  const me = await serverGet("/api/v1/me", {});
  const id = oidc ? claims((await cookies()).get(COOKIE.id)?.value) : null;
  const roles = (me.data?.roles ?? []).filter((r) => r.startsWith("modeler-"));
  return (
    <main data-testid="account-page">
      <Hero eyebrow="Your account" title={me.data?.name || "Your account"}
            lede={oidc ? "Signed in through your company's sign-in page." : "Development sign-in: one user, no password, not for client work."} />
      {me.problem && <ApiProblem problem={me.problem} />}
      {me.data && (
        <div className="account-grid">
          <section className="card" aria-labelledby="account-who">
            <h2 id="account-who">Who you are here</h2>
            <dl className="account-facts">
              <dt>Name</dt><dd data-testid="account-name">{me.data.name || "—"}</dd>
              {typeof id?.email === "string" && <><dt>Email</dt><dd>{id.email}</dd></>}
              <dt>Company</dt><dd data-testid="account-company">{me.data.tenant_id || "—"}</dd>
              <dt>Your id</dt><dd><code>{me.data.user_id}</code></dd>
            </dl>
          </section>
          <section className="card" aria-labelledby="account-roles">
            <h2 id="account-roles">What you can do</h2>
            <ul className="plain-list" data-testid="account-roles">
              {roles.length ? roles.map((r) => <li key={r}>{ROLES[r] ?? r}</li>) : <li>No Modeler One role yet: ask your administrator.</li>}
            </ul>
            <p className="muted">Roles are given in Admin → People. A project is changed only by its owner; the people it is
              shared with read it, and a reviewer signs it.</p>
          </section>
          <section className="card" aria-labelledby="account-session">
            <h2 id="account-session">Sign-in and security</h2>
            {oidc ? (
              <>
                <dl className="account-facts">
                  <dt>Signed in</dt><dd data-testid="account-since">{when(id?.auth_time)}</dd>
                  <dt>Session</dt><dd>Ends after 30 minutes without use; each signature asks for your password and code again.</dd>
                </dl>
                <div className="account-acts">
                  <a className="btn" href={`${oidc.issuer}/account`} target="_blank" rel="noreferrer" data-testid="account-security">
                    Change your password or authenticator
                  </a>
                  <a className="btn primary" href="/auth/logout" data-testid="account-sign-out">Sign out</a>
                </div>
                <p className="muted">Your password and authenticator are kept by your company&apos;s sign-in service, never by
                  Modeler One.</p>
              </>
            ) : (
              <p data-testid="account-dev">This server uses the development sign-in: there is no password to change and no
                session to end. Set up Keycloak (deploy/server/keycloak.sh) for named, Part 11 sign-in.</p>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
