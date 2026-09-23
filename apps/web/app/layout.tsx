import type { ReactNode } from "react";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import "./globals.css";
import { Nav } from "@/components/Nav";

// Plex was drawn for technical work: unambiguous figures, a real voice, and a mono companion for the
// identifiers in this product (parameter ids, engine paths, campaign ids) that are read character by character.
const sans = IBM_Plex_Sans({
  subsets: ["latin"], weight: ["400", "500", "600"], display: "swap", variable: "--font-sans",
});
const mono = IBM_Plex_Mono({
  subsets: ["latin"], weight: ["400", "500"], display: "swap", variable: "--font-mono",
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
          <div className="content">{children}</div>
        </div>
      </body>
    </html>
  );
}
