import { createFileRoute } from "@tanstack/react-router";

import { LandingPage } from "./marketing/_components/-landing-page";

export const Route = createFileRoute("/")({ component: MarketingPage });

function MarketingPage() {
  return <LandingPage />;
}
