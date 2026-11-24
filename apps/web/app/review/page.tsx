import { redirect } from "next/navigation";

// The review inbox is gone (the owner's decision of 2026-11-11): what waits on a person is listed, as links, on Your work
// (the console redesign, P-02). Old links and bookmarks to /review land there instead of a 404.
export default function ReviewInbox(): never {
  redirect("/work");
}
