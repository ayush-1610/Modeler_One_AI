"use client";

import { useState } from "react";

import { WEB_TOKEN } from "@/lib/writes";

const LABELS: Record<string, string> = {
  "package.zip": "Submission package (.zip)",
  "mar.pdf": "Report — PDF/A",
  "mar.docx": "Report — Word",
  "mar.md": "Report — Markdown",
};

/**
 * Download buttons for the S7 artifacts. The API needs the bearer token, which a plain link would not send, so
 * each download is fetched with it and handed to the browser as a file. The package itself is only offered when
 * its reproduction passed (decision D13) — the API refuses it otherwise.
 */
export function PackageDownloads({ campaignId, artifacts }: { campaignId: string; artifacts: string[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function download(artifact: string) {
    setBusy(artifact);
    setError(null);
    try {
      const res = await fetch(`/api/v1/campaigns/${campaignId}/package/${artifact}`, {
        headers: { Authorization: `Bearer ${WEB_TOKEN}` },
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setError(body.detail ?? `Could not download ${artifact} (${res.status}).`);
        return;
      }
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `${campaignId}-${artifact}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Could not reach the API to download the file.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
        {artifacts.map((a) => (
          <button key={a} className={`btn${a === "package.zip" ? " primary" : ""}`} disabled={busy !== null}
                  onClick={() => download(a)}>
            {busy === a ? "Preparing…" : LABELS[a] ?? a}
          </button>
        ))}
      </div>
      {error && <p className="banner warn" style={{ marginTop: 10 }} role="alert">{error}</p>}
    </div>
  );
}
