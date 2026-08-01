import { Link } from "@tanstack/react-router";

import { BrandMark } from "@/components/brand-mark";
import ThemeToggle from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";

import { AuthCta } from "./-auth-cta";

export function MarketingHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-border/70 bg-background/85 backdrop-blur-xl">
      <nav
        className="mx-auto flex h-12 max-w-6xl items-center justify-between px-4 md:px-0  md:grid md:grid-cols-[1fr_auto_1fr]   "
        aria-label="Primary navigation"
      >
        <Link
          to="/"
          className="flex w-fit items-center gap-2 uppercase font-medium tracking-tight "
        >
          <BrandMark /> <span>reviewpr</span>
        </Link>
        <div className="hidden items-center gap-2 uppercase md:flex">
          <Button
            className={"text-foreground/60"}
            size="sm"
            variant="ghost"
            render={<a href="#product" />}
          >
            Product
          </Button>
          <Button
            className={"text-foreground/60"}
            size="sm"
            variant="ghost"
            render={<a href="#how-it-works" />}
          >
            How it works
          </Button>
          <Button
            className={"text-foreground/60"}
            size="sm"
            variant="ghost"
            render={<a href="#why" />}
          >
            Why reviewpr
          </Button>
        </div>
        <div className="flex items-center justify-self-end gap-2">
          <ThemeToggle />
          <AuthCta compact />
        </div>
      </nav>
    </header>
  );
}
