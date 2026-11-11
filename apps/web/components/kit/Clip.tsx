// Long recorded text, said in one line (the 2026-11-11 audit, item 1): a record's change reason or an audit reason can
// carry a whole value as JSON (an expression profile is thousands of characters). The line keeps what it is about and how
// long the rest is; the whole text stays one click away, unchanged, in a scrollable box. Nothing is cut from the record.

const MAX = 140;

/** What the text is about: the part before a value (`proposed expr.profile.ABCB1 = {…}` → `proposed expr.profile.ABCB1`). */
function head(text: string, max: number): { lead: string; rest: number } {
  const value = text.search(/\s=\s*[[{]/);
  if (value > 0 && value <= max) return { lead: text.slice(0, value), rest: text.length - value };
  return { lead: `${text.slice(0, max).trimEnd()}…`, rest: text.length - max };
}

/** `lead`, when given, says what the text is (a structured value's one-line summary) and the whole text is behind it. */
export function Clip({ text, max = MAX, testId, lead: said }: {
  text: string | null | undefined; max?: number; testId?: string; lead?: string;
}) {
  if (!text) return <span className="muted">—</span>;
  if (said === undefined && text.length <= max) return <span data-testid={testId}>{text}</span>;
  const { lead, rest } = said === undefined ? head(text, max) : { lead: said, rest: text.length };
  return (
    <details className="clip" data-testid={testId}>
      <summary>
        <span className="clip-lead">{lead}</span>{" "}
        <span className="clip-more">+ {rest.toLocaleString()} characters · show all</span>
      </summary>
      <pre className="clip-full">{text}</pre>
    </details>
  );
}
