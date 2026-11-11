import { PageSkeleton } from "@/components/kit/Skeleton";

// A project's page while it is read: its head, the step bar and its cards, in skeleton (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="run" eyebrow="Project" stepper body="cards" />;
}
