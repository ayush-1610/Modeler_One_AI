import { PageSkeleton } from "@/components/kit/Skeleton";

// A campaign's monitor while it is read (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="run" eyebrow="Campaign" body="cards" />;
}
