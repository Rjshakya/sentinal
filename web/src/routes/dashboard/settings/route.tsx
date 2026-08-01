import { createFileRoute } from "@tanstack/react-router";

import { Skeleton } from "@/components/ui/skeleton";
import { protectPage } from "@/lib/auth";
import { useLlmConfig } from "@/lib/llm";

import { LlmConfigCard } from "./_components/-llm-config-card";

export const Route = createFileRoute("/dashboard/settings")({
  component: SettingsPage,
  beforeLoad: protectPage,
  ssr: false,
});

function SettingsPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Manage how Sentinel reviews your pull requests.
        </p>
      </div>
      <LlmConfigSection />
    </div>
  );
}

function LlmConfigSection() {
  const { data: rows, isLoading } = useLlmConfig();
  if (isLoading) return <Skeleton className="h-64 w-full" />;
  return <LlmConfigCard existing={rows?.[0] ?? null} />;
}
