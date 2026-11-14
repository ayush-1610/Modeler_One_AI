import { PageSkeleton } from "@/components/kit/Skeleton";

// A project's page while it is read: its head, the step bar and its cards, in skeleton (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="run" eyebrow="Step 4 of 4 · Run" stepper body="cards" />;
}
