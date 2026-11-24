import { PageSkeleton } from "@/components/kit/Skeleton";

// A project's agent runs while they are read.
export default function Loading() {
  return <PageSkeleton tone="history" eyebrow="Project record" title="Agent activity" />;
}
