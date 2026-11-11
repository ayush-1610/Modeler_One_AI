import { PageSkeleton } from "@/components/kit/Skeleton";

// A project's history while it is read (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="history" eyebrow="Project record" title="History" stepper />;
}
