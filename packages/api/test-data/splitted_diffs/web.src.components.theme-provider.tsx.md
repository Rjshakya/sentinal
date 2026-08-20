### web/src/components/theme-provider.tsx

```diff

deleted file mode 100644
index 1a3e059..0000000
--- a/web/src/components/theme-provider.tsx
+++ /dev/null
@@ -1,61 +0,0 @@
    2       -import { createContext, useCallback, useContext, useEffect, useState } from "react";
    3       -
    4       -export type ThemeMode = "light" | "dark";
    5       -
    6       -const STORAGE_KEY = "theme";
    7       -
    8       -interface ThemeContextValue {
    9       -  mode: ThemeMode;
   10       -  setMode: (mode: ThemeMode) => void;
   11       -  toggleMode: () => void;
   12       -}
   13       -
   14       -const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);
   15       -
   16       -function getInitialMode(): ThemeMode {
   17       -  if (typeof window === "undefined") {
   18       -    return "dark";
   19       -  }
   20       -
   21       -  return window.localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
   22       -}
   23       -
   24       -function applyThemeMode(mode: ThemeMode) {
   25       -  document.documentElement.classList.remove("light", "dark");
   26       -  document.documentElement.classList.add(mode);
   27       -  document.documentElement.setAttribute("data-theme", mode);
   28       -  document.documentElement.style.colorScheme = mode;
   29       -}
   30       -
   31       -export function ThemeProvider({ children }: { children: React.ReactNode }) {
   32       -  const [mode, setMode] = useState<ThemeMode>(() => getInitialMode());
   33       -
   34       -  useEffect(() => {
   35       -    applyThemeMode(mode);
   36       -  }, [mode]);
   37       -
   38       -  const updateMode = useCallback((nextMode: ThemeMode) => {
   39       -    setMode(nextMode);
   40       -    window.localStorage.setItem(STORAGE_KEY, nextMode);
   41       -  }, []);
   42       -
   43       -  const toggleMode = useCallback(() => {
   44       -    updateMode(mode === "light" ? "dark" : "light");
   45       -  }, [mode, updateMode]);
   46       -
   47       -  const value: ThemeContextValue = {
   48       -    mode,
   49       -    setMode: updateMode,
   50       -    toggleMode,
   51       -  };
   52       -
   53       -  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
   54       -}
   55       -
   56       -export function useTheme(): ThemeContextValue {
   57       -  const context = useContext(ThemeContext);
   58       -  if (!context) {
   59       -    throw new Error("useTheme must be used within a ThemeProvider");
   60       -  }
   61       -  return context;
   62       -}

```
