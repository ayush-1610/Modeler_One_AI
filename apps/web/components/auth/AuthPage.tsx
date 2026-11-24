// The frame of the pages someone sees before or after the app (sign in, signed out, no access): the product's mark and
// name above one card, on the calm canvas, without the sidebar (proxy.ts draws them bare). The same look as the
// sign-in form at Keycloak (deploy/keycloak/themes/modeler-one), so the way in reads as one product.

import type { ReactNode } from "react";

export function AuthPage({ title, children, testId }: { title: string; children: ReactNode; testId: string }) {
  return (
    <main className="auth-page" data-testid={testId}>
      <div className="auth-brand">
        {/* the app's own icon (app/icon.svg), served at /icon.svg even before signing in (proxy.ts) */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/icon.svg" alt="" width={40} height={40} />
        <span>Modeler One</span>
      </div>
      <section className="auth-card" aria-labelledby="auth-title">
        <h1 id="auth-title">{title}</h1>
        {children}
      </section>
      <p className="auth-foot">PBPK modelling on the Open Systems Pharmacology Suite</p>
    </main>
  );
}
