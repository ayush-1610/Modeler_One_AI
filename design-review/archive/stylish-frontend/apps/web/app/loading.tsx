import { PageSkeleton } from "@/components/kit/Skeleton";

// What the page area shows while a server-rendered page is read and no route below has its own skeleton: skeleton rows
// with a light sweeping across, never placeholder figures that could be taken for results.
export default function Loading() {
  return <PageSkeleton />;
}
