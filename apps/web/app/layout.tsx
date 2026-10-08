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
import { Nav } from "@/components/Nav";
import { Providers } from "@/components/Providers";

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

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`}>
      <body>
        <div className="app">
          <Nav />
          <div className="content"><Providers>{children}</Providers></div>
        </div>
      </body>
    </html>
  );
}
