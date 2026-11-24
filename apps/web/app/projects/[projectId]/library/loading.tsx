import { PageSkeleton } from "@/components/kit/Skeleton";

// The project's document library while it is read (audit item 9).
export default function Loading() {
  return <PageSkeleton tone="library" eyebrow="Project record" title="Documents" />;
}
