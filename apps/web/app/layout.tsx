import type { ReactNode } from "react";

export const metadata = {
  title: "Modeler One",
  description: "PBPK modeling and simulation on the Open Systems Pharmacology Suite",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif", paddingInline: 16 }}>{children}</body>
    </html>
  );
}
