import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type ThemeMode = "light" | "dark";
export type ContrastMode = "normal" | "high";

interface ThemeState {
  theme: ThemeMode;
  contrast: ContrastMode;
  setTheme: (theme: ThemeMode) => void;
  setContrast: (contrast: ContrastMode) => void;
}

const ThemeContext = createContext<ThemeState | null>(null);

const THEME_KEY = "agentqa.theme";
const CONTRAST_KEY = "agentqa.contrast";

function readStored(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeMode>(
    () => readStored(THEME_KEY, "light") as ThemeMode,
  );
  const [contrast, setContrastState] = useState<ContrastMode>(
    () => readStored(CONTRAST_KEY, "normal") as ContrastMode,
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      return;
    }
  }, [theme]);

  useEffect(() => {
    document.documentElement.dataset.contrast = contrast;
    try {
      window.localStorage.setItem(CONTRAST_KEY, contrast);
    } catch {
      return;
    }
  }, [contrast]);

  return (
    <ThemeContext.Provider
      value={{
        theme,
        contrast,
        setTheme: setThemeState,
        setContrast: setContrastState,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeState {
  const state = useContext(ThemeContext);
  if (state === null) {
    throw new Error("ThemeProvider chưa được cấu hình");
  }
  return state;
}
