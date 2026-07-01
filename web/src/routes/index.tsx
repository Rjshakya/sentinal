import { createFileRoute, useNavigate } from "@tanstack/react-router";

export const Route = createFileRoute("/")({ component: MarketingPage });

function MarketingPage() {}
