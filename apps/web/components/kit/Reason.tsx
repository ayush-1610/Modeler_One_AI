"use client";

// The reason a decision is made with (plan 2026-11-14 slice 4; the design text's kit `Reason`), kept on the audit trail.
// Suggestion chips and a "use last" chip (the last reason given for the same kind of decision in this project, in this
// browser tab) only fill the field: nothing is sent until the person presses the button, and the reason stays required
// and editable (Part 11: the person states why; the page never states it for them). The button stays enabled: pressed
// with something missing, an inline message names it, read with the field (aria-describedby). `ReasonForm` is the
// decision form every decision on Inputs is made with (components/delivery/shared.tsx `Why` renders it).

import { useEffect, useId, useState, type ReactNode, type Ref } from "react";

const STORE = "modeler.reason";

/** The project the page is about (`/projects/<id>/…`), so the last reason is never offered in another project. */
function project(): string {
  if (typeof window === "undefined") return "";
  return /^\/projects\/([^/]+)/.exec(window.location.pathname)?.[1] ?? "";
}

/** The last reason given for decisions of this kind in this project, in this browser tab (null when none, or when the
 *  browser keeps nothing). */
export function lastReason(kind: string): string | null {
  try {
    return window.sessionStorage.getItem(`${STORE}:${project()}:${kind}`);
  } catch {
    return null;
  }
}

export function rememberReason(kind: string, text: string) {
  try {
    if (text.trim()) window.sessionStorage.setItem(`${STORE}:${project()}:${kind}`, text.trim());
  } catch {
    /* a browser that keeps nothing: the chip is not offered */
  }
}

/** The reason field with its chips. `kind` keys the "use last" chip (decisions of one kind share it). */
export function ReasonField({ value, onChange, label, placeholder, suggestions = [], kind, testId, describedBy, invalid = false,
                              autoFocus = false, inputRef }: {
  value: string; onChange: (text: string) => void;
  /** what the reason is for, read aloud with the field */
  label: string;
  placeholder?: string;
  /** reasons that fit this decision, offered as chips that fill the field */
  suggestions?: string[];
  kind?: string;
  testId?: string;
  describedBy?: string;
  invalid?: boolean;
  autoFocus?: boolean;
  inputRef?: Ref<HTMLInputElement>;
}) {
  const [last, setLast] = useState<string | null>(null);
  // read once the page is in the browser (the server has no session storage)
  useEffect(() => { if (kind) setLast(lastReason(kind)); }, [kind]);
  const chips = [...new Set(suggestions.filter((s) => s.trim()))].filter((s) => s !== last);
  // the chips' test ids are the form's: `<form>-last`, `<form>-suggest-<n>` beside `<form>-why`
  const base = testId?.replace(/-why$/, "");
  return (
    <span className="reason">
      <input ref={inputRef} type="text" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} autoFocus={autoFocus}
             placeholder={placeholder} data-testid={testId} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
      {(chips.length > 0 || last) && (
        <span className="reason-chips" role="group" aria-label="Reasons to start from">
          {last && last !== value && (
            <button type="button" className="reason-chip last" onClick={() => onChange(last)} data-testid={base && `${base}-last`}
                    aria-label={`Use the last reason: ${last}`} title={last}>use last: {last.length > 40 ? `${last.slice(0, 38)}…` : last}</button>
          )}
          {chips.map((s, i) => (
            <button key={s} type="button" className="reason-chip" onClick={() => onChange(s)} aria-label={`Use the reason: ${s}`}
                    data-testid={base && `${base}-suggest-${i}`} aria-pressed={value === s}>{s}</button>
          ))}
        </span>
      )}
    </span>
  );
}

/** A decision with its reason (what the API asks `why` for). Its test ids are `${testId}-why` (the field) and
 *  `${testId}-submit` (the button). */
export function ReasonForm({ action, actionLabel, label, busy, onSubmit, onCancel, testId, optional = false, placeholder, children,
                             disabled = false, missing = null, autoFocus = false, suggestions, kind }: {
  action: string;
  /** the button's name with its context, where the same button is repeated ("Link the 76 values of 230-23.xlsx") */
  actionLabel?: string;
  label: string;
  busy: boolean;
  onSubmit: (why: string) => void | Promise<unknown>;
  onCancel?: () => void;
  testId?: string;
  /** the API takes this decision without a reason */
  optional?: boolean;
  placeholder?: string;
  /** more fields of the decision, before its reason */
  children?: ReactNode;
  /** the button cannot be pressed (a form whose own fields are not complete says why beside them) */
  disabled?: boolean;
  /** what the decision still needs besides its reason, in words ("Pick a study or a product"): said when pressed */
  missing?: string | null;
  /** the reason field takes the focus when the form opens (a form opened by a button that then goes away) */
  autoFocus?: boolean;
  suggestions?: string[];
  /** the kind of decision, for the "use last" chip; by default its button's word */
  kind?: string;
}) {
  const [why, setWhy] = useState("");
  const [said, setSaid] = useState<string | null>(null);
  const message = useId();
  const sort = kind ?? action.replace(/\d+/g, "#");
  const lacking = missing ?? (!optional && !why.trim() ? "Give the reason: it is kept on the audit trail." : null);
  return (
    <form className="delivery-why" data-testid={testId}
          onSubmit={(e) => {
            e.preventDefault();
            if (disabled || busy) return;
            setSaid(lacking);
            if (lacking) return;
            rememberReason(sort, why);
            void onSubmit(why.trim());
          }}>
      {children}
      <ReasonField value={why} onChange={(t) => { setWhy(t); if (said) setSaid(null); }} label={label} kind={sort} suggestions={suggestions}
                   placeholder={placeholder ?? (optional ? "a note (optional)" : "why (kept on the audit trail)")}
                   testId={testId && `${testId}-why`} describedBy={said ? message : undefined} invalid={Boolean(said)} autoFocus={autoFocus} />
      {/* while the decision is sent the button stays focusable (aria-disabled, the submit ignored): a disabled button
          would drop the focus to the page, out of a dialog */}
      <button type="submit" className="btn small primary" disabled={disabled} aria-disabled={busy || undefined} aria-label={actionLabel}
              aria-describedby={said ? message : undefined} data-testid={testId && `${testId}-submit`}>{action}</button>
      {onCancel && <button type="button" className="btn small" onClick={onCancel}>Cancel</button>}
      {said && <span id={message} className="reason-missing" role="alert" data-testid={testId && `${testId}-missing`}>{said}</span>}
    </form>
  );
}
