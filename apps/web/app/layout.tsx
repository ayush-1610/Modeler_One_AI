import type { ReactNode } from "react";
import localFont from "next/font/local";

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
import { THEME_BOOT } from "@/components/kit/ThemeToggle";
import { Nav } from "@/components/Nav";
import { Providers } from "@/components/Providers";
import { signedInName } from "@/lib/session";

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
  return (
    // the saved theme is applied before the first paint (THEME_BOOT), so <html> may differ from the server's render
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} /></head>
      <body>
        {/* the first Tab stop: past the sidebar to the page (every page renders its own <main>) */}
        <a className="skip-link" href="#content">Skip to the page</a>
        {/* the sidebar is inside the providers too: its "Add data" card changes the project and refreshes the page */}
        <Providers>
          <div className="app">
            <Nav user={user} />
            <div className="content">
              <span id="content" tabIndex={-1} className="skip-target" />
              {children}
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
