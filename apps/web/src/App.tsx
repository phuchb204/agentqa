import { useEffect, useRef, useState } from "react";
import { QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";

import { createApiClient, type ApiClient } from "./api/client";
import { ApiProvider } from "./api/context";
import type { SessionInfo } from "./api/types";
import { LoadingView } from "./components/States";
import { createQueryClient } from "./app/queryClient";
import { createAppRouter } from "./app/router";
import { SessionProvider } from "./app/session-context";
import { LoginView } from "./app/shell/LoginView";
import { ThemeProvider } from "./app/theme";

const BOOTSTRAP_PREFIX = "#bootstrap=";

function consumeBootstrapNonce(): string | null {
  const hash = window.location.hash;
  if (!hash.startsWith(BOOTSTRAP_PREFIX)) {
    return null;
  }
  const nonce = hash.slice(BOOTSTRAP_PREFIX.length);
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  return nonce;
}

function AuthenticatedApp({ user, logout }: { user: SessionInfo; logout: () => Promise<void> }) {
  const queryClient = useQueryClient();
  const [router] = useState(() => createAppRouter({ queryClient }));
  return (
    <SessionProvider value={{ user, logout }}>
      <RouterProvider router={router} />
    </SessionProvider>
  );
}

function SessionGate({ api, csrfRef }: { api: ApiClient; csrfRef: { current: string | null } }) {
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<SessionInfo | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      const nonce = consumeBootstrapNonce();
      if (nonce !== null) {
        try {
          const result = await api.localBootstrap(nonce);
          if (!active) {
            return;
          }
          csrfRef.current = result.csrfToken;
          setUser(result.user);
          setReady(true);
          return;
        } catch {
          // bootstrap thất bại thì rơi về kiểm tra session hiện có
        }
      }
      try {
        const session = await api.session();
        if (session !== null) {
          try {
            await api.ensureCsrf();
          } catch {
            // PAT hoặc môi trường không cookie: bỏ qua, mutation sẽ báo lỗi rõ
          }
        }
        if (active) {
          setUser(session);
          setReady(true);
        }
      } catch {
        if (active) {
          setUser(null);
          setReady(true);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [api, csrfRef]);

  async function logout() {
    try {
      await api.logout();
    } finally {
      csrfRef.current = null;
      setUser(null);
    }
  }

  if (!ready) {
    return <LoadingView label="Đang kiểm tra phiên làm việc" />;
  }
  if (user === null) {
    return (
      <LoginView
        api={api}
        onSuccess={(result) => {
          csrfRef.current = result.csrfToken;
          setUser(result.user);
        }}
      />
    );
  }
  return <AuthenticatedApp user={user} logout={logout} />;
}

export function App({ clientOverride }: { clientOverride?: ApiClient } = {}) {
  const csrfRef = useRef<string | null>(null);
  const [api] = useState<ApiClient>(
    () =>
      clientOverride ??
      createApiClient({
        getCsrf: () => csrfRef.current,
        setCsrf: (token) => {
          csrfRef.current = token;
        },
      }),
  );
  const [queryClient] = useState(() => createQueryClient());
  return (
    <ApiProvider client={api}>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>
          <SessionGate api={api} csrfRef={csrfRef} />
        </ThemeProvider>
      </QueryClientProvider>
    </ApiProvider>
  );
}
