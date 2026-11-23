"use client";

// What a reading of a sheet left out and what it changed, cell by cell (plan 2026-11-05 §3.1 step 4: "cleaned, with a
// record ... nothing silently"; `modeler_intake.cleaning`): the title and notes around the table, empty rows, columns
// not read, cells with no sample, cells below the LLOQ kept as such, text that is not a number, decimal commas read.

export type CleaningLine = { kind: "ignored" | "not_read" | "no_sample" | "below_lloq" | "corrected"; text: string; cells: string[] };

const KIND: Record<CleaningLine["kind"], { label: string; tone: string }> = {
  ignored: { label: "left out", tone: "neutral" }, not_read: { label: "not read", tone: "medium" },
  no_sample: { label: "no sample", tone: "neutral" }, below_lloq: { label: "below LLOQ", tone: "neutral" },
  corrected: { label: "corrected", tone: "brand" },
};

const cell = (ref: string) => ref.split("!").pop();

export function CleaningRecord({ lines, testId, open = false }: { lines: CleaningLine[] | undefined; testId: string; open?: boolean }) {
  if (!lines?.length) return null;
  return (
    <details className="cleaning-record" data-testid={testId} open={open}>
      <summary>What the reading left out and changed ({lines.length})</summary>
      <ul>
        {lines.map((line) => (
          <li key={line.text}>
            <span className={`chip ${KIND[line.kind].tone}`}>{KIND[line.kind].label}</span>{" "}
            {line.text}
            {line.cells.length > 0 && <span className="muted cleaning-cells"> {line.cells.map(cell).join(", ")}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}
