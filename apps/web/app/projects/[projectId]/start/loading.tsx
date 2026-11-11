import { PageSkeleton } from "@/components/kit/Skeleton";

// Start while it is read (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="start" eyebrow="Step 1 of 4 · Start" title="Start" stepper />;
}
