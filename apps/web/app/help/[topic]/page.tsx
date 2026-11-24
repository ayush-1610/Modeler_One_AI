import { notFound } from "next/navigation";

import { HelpPage } from "@/components/portfolio/Help";
import { HELP_TOPICS } from "@/lib/help";

export default async function HelpTopic({ params }: { params: Promise<{ topic: string }> }) {
  const { topic } = await params;
  if (!HELP_TOPICS.some((t) => t.id === topic)) notFound();
  return <HelpPage topic={topic} />;
}
