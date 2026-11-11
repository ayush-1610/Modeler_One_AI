import { PageSkeleton } from "@/components/kit/Skeleton";

// Review & sign while it is read: the canvas's place held by one block (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="review" eyebrow="Step 3 · Review & sign" title="Review & sign" stepper body="canvas" wide />;
}
