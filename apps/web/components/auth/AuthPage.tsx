// The frame of the pages someone sees before or after the app (sign in, signed out, no access): the owner's split
// sign-in design (2026-11-27, the Graphite sign-off): a full-screen abstract background (self-hosted, no outside image),
// the product's words on the left, one frosted card on the right; stacked on a phone. No sidebar (proxy.ts draws these
// bare). Keycloak's form wears the same design (deploy/keycloak/themes/modeler-one), so the way in reads as one product.
// The password is typed at Keycloak, never on these pages (21 CFR Part 11; CLAUDE.md).

import type { ReactNode } from "react";

import { Logo } from "@/components/Nav";

/** Where the card is: on the right on a wide window, below it on a phone (auth.css shows one of the two). */
export function Where({ wide = "on the right side", narrow = "below" }: { wide?: string; narrow?: string }) {
  return <><span className="auth-wide">{wide}</span><span className="auth-narrow">{narrow}</span></>;
}

export function AuthPage({ title, lede = <>Please fill the form <Where />.</>, children, testId }: {
  title: string; lede?: ReactNode; children: ReactNode; testId: string;
}) {
  return (
    <main className="auth-split" data-testid={testId}>
      <section className="auth-hero" aria-label="Modeler One">
        <div className="auth-brand"><Logo size={30} light /><span>Modeler One</span></div>
        <p className="auth-hero-title">Whatever happens here, <em>stays</em> here</p>
        <p className="auth-hero-sub">{lede}</p>
      </section>
      <section className="auth-card" aria-labelledby="auth-title">
        <h1 id="auth-title">{title}</h1>
        {children}
        <p className="auth-ask">No account, or forgot your password? Ask your Modeler One administrator.</p>
      </section>
    </main>
  );
}
