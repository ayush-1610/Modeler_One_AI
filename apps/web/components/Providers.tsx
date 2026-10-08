"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

/** The browser's resource cache for `useResource` / `useMutation` (lib/hooks.ts), one per tab. A read shows its
 *  problem at once (no retries) and is fetched again only when a change asks for it, never on window focus, so what a
 *  reviewer sees changes only when something changed it. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
