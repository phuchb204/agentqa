import { createContext, useContext } from "react";

import type { SessionInfo } from "../api/types";

export interface SessionContextValue {
  user: SessionInfo;
  logout: () => Promise<void>;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export const SessionProvider = SessionContext.Provider;

export function useSession(): SessionContextValue {
  const value = useContext(SessionContext);
  if (value === null) {
    throw new Error("SessionProvider chưa được cấu hình");
  }
  return value;
}
