import type { ReactNode } from "react";
import localFont from "next/font/local";

import "./globals.css";
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
