import type { ReactElement, ReactNode } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { SessionProvider } from "../app/session-context";
import { ThemeProvider } from "../app/theme";

export function renderWithProviders(
  ui: ReactElement,
  { client, username = "tester" }: { client: ApiClient; username?: string },
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ApiProvider client={client}>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            <SessionProvider
              value={{ user: { user_id: "u1", username }, logout: async () => undefined }}
            >
              {children}
            </SessionProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </ApiProvider>
    );
  }
  return render(ui, { wrapper: Wrapper });
}
