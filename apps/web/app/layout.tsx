import type { ReactNode } from "react";

import "./globals.css";
import { Nav } from "@/components/Nav";

export const metadata = {
  title: "Modeler One",
  description: "PBPK modeling and simulation on the Open Systems Pharmacology Suite",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="app">
          <Nav />
          <div className="content">{children}</div>
        </div>
      </body>
    </html>
  );
}
