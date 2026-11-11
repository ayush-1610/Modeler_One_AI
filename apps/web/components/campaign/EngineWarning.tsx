// What produced a campaign's numbers, when it was not PK-Sim (CLAUDE.md: a result counts only if it ran on real PK-Sim).
// The campaign page and the escalation dialog show the same warning, so a decision is never signed over fixture numbers
// without saying so (the 2026-11-11 audit, item 5).

import type { EngineIdentity } from "@/lib/types";

export function EngineWarning({ engine, testId = "engine-warning", className = "mb-14" }: {
  engine: EngineIdentity | null | undefined; testId?: string; className?: string;
}) {
  if (!engine || engine.kind === "pksim") return null;
  return (
    <div className={`banner err ${className}`} role="note" data-testid={testId}>
      {engine.kind === "software-fixture"
        ? <>Not a PBPK result: this campaign ran on a software test fixture (<code>{engine.command}</code>). Its
            curves are synthetic; it checks the software path only. Run on PK-Sim for model evidence.</>
        : <>The engine this campaign ran on is not identified as PK-Sim (<code>{engine.command}</code>). Treat
            its numbers as unverified.</>}
    </div>
  );
}
