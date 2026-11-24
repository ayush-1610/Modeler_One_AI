// A record's status in a word and a colour (design-review/DESIGN_SYSTEM.md §5.3): green for done, blue while it runs,
// amber when it waits on a person, red when it stopped. It replaced `components/ui.tsx` `StatusChip` in the console
// redesign's slice 9.

const TONE: Record<string, string> = {
  PASSED: "low", ACCEPTED: "low", COMPLETED: "low", RUNNING: "brand",
  ESCALATED: "high", REJECTED: "high", FAILED: "high", ABORTED: "high", PROPOSED: "medium",
  SKIPPED: "neutral", AWAITING_SIGNATURE: "medium",
  APPROVED: "low", DRAFT: "medium", STALE: "high", SUPERSEDED: "neutral", IN_REVIEW: "medium",
};

export function StatusIndicator({ status }: { status: string }) {
  return <span className={`chip ${TONE[status] ?? "neutral"}`}>{status.toLowerCase()}</span>;
}
