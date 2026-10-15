// The signing step-up in the browser. An electronic signature needs the person to confirm their identity again
// (password and authenticator code, acr loa2; 21 CFR 11.200). When the API refuses a signature for want of it
// (403 STEP_UP_REQUIRED or STEP_UP_STALE), the API client asks here; the StepUpDialog mounted in Providers shows why,
// opens Keycloak's step-up in a small window on the person's click (so the page keeps what they typed), and answers
// once Keycloak is done. The client then sends the signature again, once.

type Answer = (confirmed: boolean) => void;

let show: ((answer: Answer) => void) | null = null;

/** The dialog registers itself here; the returned function unregisters it. */
export function registerStepUpDialog(open: (answer: Answer) => void): () => void {
  show = open;
  return () => { if (show === open) show = null; };
}

/** Ask the person to confirm their identity; true once they did. False when they cancel or no dialog is mounted. */
export function requestStepUp(): Promise<boolean> {
  if (typeof window === "undefined" || !show) return Promise.resolve(false);
  const open = show;
  return new Promise((resolve) => open(resolve));
}

export const STEP_UP_CODES = ["STEP_UP_REQUIRED", "STEP_UP_STALE"];
