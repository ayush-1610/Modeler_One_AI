import { redirect } from "next/navigation";

// The review inbox is gone (the owner's decision of 2026-11-11): an open escalation is asked for on whatever page the
// person is on (EscalationPopup, mounted in the root layout), and the dashboard's "Needs your attention" links each one
// to its campaign. Old links and bookmarks to /review land on the dashboard instead of a 404.
export default function ReviewInbox(): never {
  redirect("/");
}
