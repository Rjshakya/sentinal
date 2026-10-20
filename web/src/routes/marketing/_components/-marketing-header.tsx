import { Link } from "@tanstack/react-router";

import { BrandMark } from "@/components/brand-mark";

import { AuthCta } from "./-auth-cta";

export function MarketingHeader() {
  return (
    <header className="sticky top-0 z-50   bg-black">
      <nav
        className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between px-4 sm:px-6 md:px-8"
        aria-label="Primary navigation"
      >
        <Link to="/" className="flex w-fit items-center" aria-label="ReviewPR home">
          <BrandMark />
        </Link>
        <div className="flex items-center">
          <AuthCta compact />
        </div>
      </nav>
    </header>
  );
}
