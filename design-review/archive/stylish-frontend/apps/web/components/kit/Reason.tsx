"use client";

// The reason a decision is made with (plan 2026-11-14 slice 4; the design text's kit `Reason`), kept on the audit trail.
// Suggestion chips and a "use last" chip (the last reason the same person gave for the same kind of decision in this
// project, in this browser tab) only fill the field: nothing is sent until the person presses the button, and the reason
// stays required and editable (Part 11: the person states why; the page never states it for them). The button stays
// enabled: pressed with something missing, an inline message names it, read with the button and, when the reason is what
// is missing, with the field (aria-describedby, aria-invalid); pressed again, it is said again. Once a decision is made,
// the field is emptied: the next decision's reason is typed or taken from "use last", never carried over unseen (final
// review CODE-7). The last reasons are keyed by the person signed in and the kind of decision, and forgotten at sign-out
// (final review INT-12). `ReasonForm` is the decision form every decision on Inputs is made with
// (components/delivery/shared.tsx `Why` renders it).

import { createContext, useContext, useEffect, useId, useState, type ReactNode, type Ref } from "react";

const STORE = "modeler.reason";
const REASON_MISSING = "Give the reason: it is kept on the audit trail.";

/** Who is signed in (the ID token's subject; "" with the DEV sign-in), given by the root layout: a last reason is offered
 *  only to the person who gave it. */
export const ReasonPerson = createContext("");

/** The project the page is about (`/projects/<id>/…`), so the last reason is never offered in another project. */
function project(): string {
  if (typeof window === "undefined") return "";
  return /^\/projects\/([^/]+)/.exec(window.location.pathname)?.[1] ?? "";
}

/** A short stand-in for the person (FNV-1a), so their id is not written into the tab's storage keys. */
function tag(person: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < person.length; i++) h = Math.imul(h ^ person.charCodeAt(i), 0x01000193);
  return (h >>> 0).toString(36);
}

const keyOf = (person: string, kind: string) => `${STORE}:${tag(person)}:${project()}:${kind}`;

/** The last reason this person gave for decisions of this kind in this project, in this browser tab (null when none, or
 *  when the browser keeps nothing). */
export function lastReason(person: string, kind: string): string | null {
  try {
    return window.sessionStorage.getItem(keyOf(person, kind));
  } catch {
    return null;
  }
}

export function rememberReason(person: string, kind: string, text: string) {
  try {
    if (text.trim()) window.sessionStorage.setItem(keyOf(person, kind), text.trim());
  } catch {
    /* a browser that keeps nothing: the chip is not offered */
  }
}

/** Forget every last reason the tab keeps (at sign-out: the next person in this tab is never offered them). */
export function forgetReasons() {
  try {
    const store = window.sessionStorage;
    const keys = Array.from({ length: store.length }, (_, i) => store.key(i)).filter((k): k is string => Boolean(k?.startsWith(`${STORE}:`)));
    for (const k of keys) store.removeItem(k);
  } catch {
    /* nothing kept */
  }
}

/** Whether a decision's answer says it was made: `true`, or a decision's outcome with its answer (`{ data }`, no
 *  `problem`). Anything else (a refusal, nothing said) keeps the reason in the field, so the person can press again. */
function made(result: unknown): boolean {
  if (result === true) return true;
  if (!result || typeof result !== "object" || !("data" in result)) return false;
  const r = result as { problem?: unknown; data?: unknown };
  return r.data !== null && r.data !== undefined && !r.problem;
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
  const person = useContext(ReasonPerson);
  const [last, setLast] = useState<string | null>(null);
  const empty = value === "";
  // read once the page is in the browser (the server has no session storage), again when the field is emptied (a
  // decision was made) and when it takes the focus (a reason given in another form since)
  useEffect(() => { if (kind) setLast(lastReason(person, kind)); }, [kind, person, empty]);
  const chips = [...new Set(suggestions.filter((s) => s.trim()))].filter((s) => s !== last);
  // the chips' test ids are the form's: `<form>-last`, `<form>-suggest-<n>` beside `<form>-why`
  const base = testId?.replace(/-why$/, "");
  return (
    <span className="reason">
      <input ref={inputRef} type="text" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} autoFocus={autoFocus}
             onFocus={() => { if (kind) setLast(lastReason(person, kind)); }}
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
export function ReasonForm({ action, actionLabel, label, busy, onSubmit, onCancel, testId, formTestId, optional = false, placeholder,
                             children, disabled = false, missing = null, autoFocus = false, suggestions, kind }: {
  action: string;
  /** the button's name with its context, where the same button is repeated ("Link the 76 values of 230-23.xlsx") */
  actionLabel?: string;
  label: string;
  busy: boolean;
  /** the decision: `true` or its outcome (`useDecide`'s `{ data, problem }`) says it was made, and the field is emptied;
   *  anything else keeps the reason for the next press */
  onSubmit: (why: string) => unknown;
  onCancel?: () => void;
  testId?: string;
  /** the form's own testid, where `testId` names a wrapper around it (its field and button keep `testId`'s prefix) */
  formTestId?: string;
  /** the API takes this decision without a reason */
  optional?: boolean;
  placeholder?: string;
  /** more fields of the decision, before its reason */
  children?: ReactNode;
  /** the button cannot be pressed: only the layout form, whose own fields say beside them why (plan §5); every other form
   *  names what is missing with `missing` */
  disabled?: boolean;
  /** what the decision still needs besides its reason, in words ("Pick a study or a product"): said when pressed */
  missing?: string | null;
  /** the reason field takes the focus when the form opens (a form opened by a button that then goes away) */
  autoFocus?: boolean;
  suggestions?: string[];
  /** the kind of decision ("link", "not data", "fact entered"): keys the "use last" chip, so a reason is offered again
   *  only for the same kind of decision, never because two buttons share a word */
  kind: string;
}) {
  const person = useContext(ReasonPerson);
  const [why, setWhy] = useState("");
  // what the last press found missing: whether it is the reason, and the press it was said on (said again on each press)
  const [said, setSaid] = useState<{ text: string; reason: boolean; press: number } | null>(null);
  const message = useId();
  const reasonLacking = !optional && !why.trim();
  const lacking = missing ?? (reasonLacking ? REASON_MISSING : null);
  // a message is shown while what it names is still missing
  const shown = said && (said.reason ? reasonLacking && !missing : missing === said.text) ? said : null;
  return (
    <form className="delivery-why" data-testid={formTestId ?? testId}
          onSubmit={async (e) => {
            e.preventDefault();
            if (disabled || busy) return;
            if (lacking) {
              setSaid((was) => ({ text: lacking, reason: !missing, press: (was?.press ?? 0) + 1 }));
              return;
            }
            setSaid(null);
            const text = why.trim();
            const result = await onSubmit(text);
            if (made(result)) {
              rememberReason(person, kind, text);
              setWhy("");
            }
          }}>
      {children}
      <ReasonField value={why} onChange={setWhy} label={label} kind={kind} suggestions={suggestions}
                   placeholder={placeholder ?? (optional ? "a note (optional)" : "why (kept on the audit trail)")}
                   testId={testId && `${testId}-why`} describedBy={shown?.reason ? message : undefined} invalid={Boolean(shown?.reason)}
                   autoFocus={autoFocus} />
      {/* while the decision is sent the button stays focusable (aria-disabled, the submit ignored): a disabled button
          would drop the focus to the page, out of a dialog */}
      <button type="submit" className="btn small primary" disabled={disabled} aria-disabled={busy || undefined} aria-label={actionLabel}
              aria-describedby={shown ? message : undefined} data-testid={testId && `${testId}-submit`}>{action}</button>
      {onCancel && <button type="button" className="btn small" onClick={onCancel}>Cancel</button>}
      {/* a new element each press, so a refusal pressed twice is said twice */}
      {shown && <span key={shown.press} id={message} className="reason-missing" role="alert" data-testid={testId && `${testId}-missing`}>{shown.text}</span>}
    </form>
  );
}
