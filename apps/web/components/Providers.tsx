"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { ReasonPerson } from "@/components/kit/Reason";
import { StepUpDialog } from "@/components/StepUpDialog";

/** The browser's resource cache for `useResource` / `useMutation` (lib/hooks.ts), one per tab. A read shows its
 *  problem at once (no retries) and is fetched again only when a change asks for it, never on window focus, so what a
 *  reviewer sees changes only when something changed it. `person`: who is signed in, so the last reason a person gave is
 *  offered to them only (components/kit/Reason.tsx). */
export function Providers({ person = "", children }: { person?: string; children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  }));
  return (
    <QueryClientProvider client={client}>
      <ReasonPerson.Provider value={person}>{children}<StepUpDialog /></ReasonPerson.Provider>
    </QueryClientProvider>
  );
}
