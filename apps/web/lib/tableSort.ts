// The pure part of a long table's sort (the 2026-11-11 audit, item 11): comparing keys, reading a number out of a
// stringified value, and an order map for a column that is not alphabetical. No React here, so server pages call it too.

export type SortKey = string | number | null | undefined;
export type SortDir = "ascending" | "descending";
export type SortState = { col: string; dir: SortDir } | null;

/** Nulls last; numbers as numbers; text by locale with numbers inside it read as numbers ("S10" after "S9"). */
export function compareKeys(a: SortKey, b: SortKey): number {
  const an = a === null || a === undefined || a === "", bn = b === null || b === undefined || b === "";
  if (an || bn) return an === bn ? 0 : an ? 1 : -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** A value that reads as a number ("0.25", "1e-3") as a number, anything else as its text. */
export function numericKey(v: unknown): SortKey {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const n = Number(String(v).trim());
  return Number.isFinite(n) && String(v).trim() !== "" ? n : String(v);
}

/** An order map for a column whose values are not alphabetical (a stage, a role, a risk): unknown values go last. */
export function ordinal(order: readonly string[]) {
  return (v: string | null | undefined): SortKey => {
    if (!v) return null;
    const i = order.indexOf(v);
    return i < 0 ? order.length : i;
  };
}
