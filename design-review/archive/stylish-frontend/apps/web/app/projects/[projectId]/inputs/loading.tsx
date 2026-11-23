import { PageSkeleton } from "@/components/kit/Skeleton";

// Inputs while it is read (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="inputs" eyebrow="Step 2 of 4" title="Inputs" stepper body="cards" />;
}
