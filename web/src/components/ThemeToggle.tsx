import { Button } from "./ui/button";
import { useTheme } from "./theme-provider";

export default function ThemeToggle() {
  const { mode, toggleMode } = useTheme();

  return (
    <Button variant={"ghost"} onClick={toggleMode}>
      {mode === "dark" ? "Dark" : "Light"}
    </Button>
  );
}
