"use client";

import { useEffect, useState } from "react";

import { Dialog } from "@/components/kit/Dialog";
import { registerStepUpDialog } from "@/lib/step-up";

type Answer = (confirmed: boolean) => void;

/** The signing step-up (lib/step-up.ts): why the identity is asked for again, and Keycloak's check in a small window
 *  opened on the person's click, so the page keeps what they typed. The signature is sent again once it is done. */
export function StepUpDialog() {
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [blocked, setBlocked] = useState(false);

  useEffect(() => registerStepUpDialog((a) => { setBlocked(false); setAnswer(() => a); }), []);
  useEffect(() => {
    if (!answer) return;
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.data?.type !== "modeler:stepped-up") return;
      answer(true);
      setAnswer(null);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [answer]);

  if (!answer) return null;
  const confirm = () => {
    const opened = window.open("/auth/login?step_up=1&popup=1", "modeler-step-up", "popup,width=520,height=720");
    setBlocked(!opened);
  };
  const cancel = () => { answer(false); setAnswer(null); };
  const here = typeof window === "undefined" ? "/" : window.location.pathname + window.location.search;
  return (
    <Dialog title="Confirm your identity to sign" onClose={cancel} above testId="step-up-dialog">
      <>
        <p className="muted">
          An electronic signature needs your password and your authenticator code again, every time (21 CFR 11.200).
          Keycloak asks for them in a small window; the signature is sent as soon as you are done.
        </p>
        {blocked && (
          <div className="banner warn" data-testid="step-up-blocked">
            Your browser blocked the window. Allow pop-ups for this site, or{" "}
            <a href={`/auth/login?step_up=1&return=${encodeURIComponent(here)}`}>confirm in this tab</a> and sign again
            afterwards (what you typed on this page is not kept).
          </div>
        )}
        <div className="dialog-actions">
          <button className="btn" onClick={cancel} data-testid="step-up-cancel">Cancel</button>
          <button className="btn primary" onClick={confirm} data-testid="step-up-confirm">Confirm identity</button>
        </div>
      </>
    </Dialog>
  );
}
