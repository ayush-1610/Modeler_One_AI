import type { ReactNode } from "react";
import localFont from "next/font/local";

// The console redesign's tokens first (design-review/DESIGN_SYSTEM.md §2-3): every colour, size and radius is one of them.
import "./styles/tokens.css";
import "./globals.css";
// One stylesheet per feature (phase 7d). They load here, after the base sheet and in this order, which is the order the
// rules had in the single sheet, so the cascade is unchanged.
import "./styles/campaign.css";
import "./styles/pipeline.css";
import "./styles/brief.css";
import "./styles/evidence.css";
import "./styles/client-data.css";
import "./styles/plan.css";
import "./styles/inputs.css";
import "./styles/kit.css";
import "./styles/start.css";
import "./styles/review.css";
import "./styles/dashboard.css";
import "./styles/admin.css";
import "./styles/delivery.css";
import "./styles/cards.css";
// To do's batch tables, the bulk bar and the reason chips (plan 2026-11-14 slice 4)
import "./styles/batch.css";
// the pages' shared layout rules (Inputs rows, Start sections, skeletons, filters); the 7 Nov look and its motion are gone
import "./styles/design.css";
// the Data room and its report (plan 2026-11-21 v2 §10): after the look, so its drawer and print layout hold
import "./styles/dataroom.css";
// target sizes (WCAG 2.2 2.5.8): after the look, so its hit areas and sizes hold
import "./styles/targets.css";
// the utilities that replaced the static inline styles (item 10); last, so each holds as the inline style did
import "./styles/utilities.css";
// the console: shell, header, panels, controls, tables, banners, dialogs (the redesign, slice 1); after every page sheet
import "./styles/console.css";
import { EscalationPopup } from "@/components/campaign/EscalationPopup";
import { Toaster } from "@/components/kit/Motion";
import { AppShell } from "@/components/shell/AppShell";
import { Providers } from "@/components/Providers";
import { signedInId, signedInName } from "@/lib/session";

// Plex was drawn for technical work: unambiguous figures, a real voice, and a mono companion for the
// identifiers in this product (parameter ids, engine paths, campaign ids) that are read character by character.
// Self-hosted (app/fonts, SIL Open Font License 1.1 in app/fonts/OFL.txt): the build and the app make no third-party
// request, and every build uses the same files.
const sans = localFont({
  src: [{ path: "./fonts/IBMPlexSans-latin-var.woff2", weight: "400 600", style: "normal" }],
  display: "swap", variable: "--font-sans",
});
const mono = localFont({
  src: [
    { path: "./fonts/IBMPlexMono-latin-400.woff2", weight: "400", style: "normal" },
    { path: "./fonts/IBMPlexMono-latin-500.woff2", weight: "500", style: "normal" },
  ],
  display: "swap", variable: "--font-mono",
});

export const metadata = {
  title: "Modeler One",
  description: "PBPK modeling and simulation on the Open Systems Pharmacology Suite",
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const user = await signedInName();
  const person = await signedInId();
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        {/* the first Tab stop: past the sidebar to the page (every page renders its own <main>) */}
        <a className="skip-link" href="#content">Skip to the page</a>
        {/* the sidebar is inside the providers too: its "Add data" card changes the project and refreshes the page */}
        <Providers person={person}>
          <Toaster />
          {/* an open escalation asks for its signed decision on any page (the review inbox is gone, 2026-11-11) */}
          <EscalationPopup />
          <AppShell user={user}>
            <span id="content" tabIndex={-1} className="skip-target" />
            {children}
          </AppShell>
        </Providers>
      </body>
    </html>
  );
}
