### web/src/components/ThemeToggle.tsx

```diff

index ca2c02d..b093ab3 100644
--- a/web/src/components/ThemeToggle.tsx
+++ b/web/src/components/ThemeToggle.tsx
@@ -1,12 +1,70 @@
          2 +import { useEffect, useState } from "react";
    2     3  import { Button } from "./ui/button";
    3       -import { useTheme } from "./theme-provider";
          4 +
          5 +type ThemeMode = "light" | "dark" | "auto";
          6 +
          7 +function getInitialMode(): ThemeMode {
          8 +  if (typeof window === "undefined") {
          9 +    return "auto";
         10 +  }
         11 +
         12 +  const stored = window.localStorage.getItem("theme");
         13 +  if (stored === "light" || stored === "dark" || stored === "auto") {
         14 +    return stored;
         15 +  }
         16 +
         17 +  return "auto";
         18 +}
         19 +
         20 +function applyThemeMode(mode: ThemeMode) {
         21 +  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
         22 +  const resolved = mode === "auto" ? (prefersDark ? "dark" : "light") : mode;
         23 +
         24 +  document.documentElement.classList.remove("light", "dark");
         25 +  document.documentElement.classList.add(resolved);
         26 +
         27 +  if (mode === "auto") {
         28 +    document.documentElement.removeAttribute("data-theme");
         29 +  } else {
         30 +    document.documentElement.setAttribute("data-theme", mode);
         31 +  }
         32 +
         33 +  document.documentElement.style.colorScheme = resolved;
         34 +}
    4    35  
    5    36  export default function ThemeToggle() {
    6       -  const { mode, toggleMode } = useTheme();
         37 +  const [mode, setMode] = useState<ThemeMode>("auto");
         38 +
         39 +  useEffect(() => {
         40 +    const initialMode = getInitialMode();
         41 +    setMode(initialMode);
         42 +    applyThemeMode(initialMode);
         43 +  }, []);
         44 +
         45 +  useEffect(() => {
         46 +    if (mode !== "auto") {
         47 +      return;
         48 +    }
         49 +
         50 +    const media = window.matchMedia("(prefers-color-scheme: dark)");
         51 +    const onChange = () => applyThemeMode("auto");
         52 +
         53 +    media.addEventListener("change", onChange);
         54 +    return () => {
         55 +      media.removeEventListener("change", onChange);
         56 +    };
         57 +  }, [mode]);
         58 +
         59 +  function toggleMode() {
         60 +    const nextMode: ThemeMode = mode === "light" ? "dark" : mode === "dark" ? "auto" : "light";
         61 +    setMode(nextMode);
         62 +    applyThemeMode(nextMode);
         63 +    window.localStorage.setItem("theme", nextMode);
         64 +  }
    7    65  
    8    66    return (
    9    67      <Button variant={"ghost"} onClick={toggleMode}>
   10       -      {mode === "dark" ? "Dark" : "Light"}
         68 +      {mode === "auto" ? "Auto" : mode === "dark" ? "Dark" : "Light"}
   11    69      </Button>
   12    70    );
   13    71  }

```
