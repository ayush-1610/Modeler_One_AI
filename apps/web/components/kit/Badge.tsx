import type { Rating } from "@/lib/api";

// Small words with a colour that say what something is (design-review/DESIGN_SYSTEM.md §5.3): a rating and where a value
// came from. They replaced `components/ui.tsx` `RiskChip` and `ProvenanceChip` in the console redesign's slice 9.

const RATINGS: readonly string[] = ["low", "medium", "high"] satisfies Rating[];

/** A rating as the record states it; a value outside low / medium / high is shown as it is, uncoloured. */
export function RiskBadge({ rating }: { rating: string | null }) {
  if (!rating) return <span className="chip neutral">not rated</span>;
  return (
    <span className={`chip ${RATINGS.includes(rating) ? rating : "neutral"}`}>
      <span className="chip-dot" aria-hidden />
      {rating}
    </span>
  );
}

const PROV_CLASS: Record<string, string> = {
  ParameterIdentification: "fitted",
  fitted: "fitted",
  measured: "measured",
  Publication: "measured",
  Database: "measured",
  predicted: "predicted",
  assumed: "predicted",
};

/** Where a value came from, as the record names it; a fitted value says it was fitted by parameter identification. */
export function ProvenanceBadge({ source }: { source: string }) {
  const cls = PROV_CLASS[source] ?? "";
  const label = source === "ParameterIdentification" ? "fitted (PI)" : source;
  return <span className={`prov ${cls}`}>{label}</span>;
}
