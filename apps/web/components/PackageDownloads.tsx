"use client";

import { useState } from "react";

import { apiFile } from "@/lib/api";

const LABELS: Record<string, string> = {
  "package.zip": "Submission package (.zip, with the PK-Sim project files)",
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
    const { file, problem } = await apiFile(`/api/v1/campaigns/${encodeURIComponent(campaignId)}/package/${encodeURIComponent(artifact)}`);
    setBusy(null);
    if (!file) {
      setError(`Could not download ${artifact}: ${problem}`);
      return;
    }
    const url = URL.createObjectURL(file);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${campaignId}-${artifact}`;
    a.click();
    URL.revokeObjectURL(url);
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
