import { PageSkeleton } from "@/components/kit/Skeleton";

// The Data room while it is read.
export default function Loading() {
  return <PageSkeleton tone="inputs" eyebrow="Step 2 of 4 · Inputs" title="Data room" stepper body="rows" />;
}
