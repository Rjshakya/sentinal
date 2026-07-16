import { GithubConnectionCard } from "@/routes/dashboard/_components/-github-connection-card";
import { protectPage } from "@/lib/auth";
import { useInstallation } from "@/lib/installation";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

export const Route = createFileRoute("/dashboard/")({
  component: DashboardOverview,
  beforeLoad: protectPage,
  ssr: false,
});

function DashboardOverview() {
  return (
    <div className="flex flex-1 flex-col gap-4 p-4 pt-0">
      <div className="grid auto-rows-min gap-4 md:grid-cols-3">
        <GithubConnectionCard />
        <div className="aspect-video rounded-xl bg-muted/50" />
        <div className="aspect-video rounded-xl bg-muted/50" />
      </div>
      <div className="min-h-screen flex-1 rounded-xl bg-muted/50 md:min-h-min" />
      <InstallResultToast />
    </div>
  );
}

function InstallResultToast() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const handled = useRef(false);

  useEffect(() => {
    if (handled.current) return;
    const params = new URLSearchParams(window.location.search);
    const result = params.get("installation");
    if (!result) return;
    handled.current = true;

    if (result === "success") {
      toast.success("GitHub App installed");
      qc.invalidateQueries({ queryKey: ["github", "installation"] });
    } else {
      const reason = params.get("reason") ?? "unknown";
      toast.error(`Install failed: ${reason}`);
    }

    void navigate({ to: "/dashboard", search: {}, replace: true });
  }, [navigate, qc]);

  // Touch the hook so the installation query is always subscribed in the
  // tree (keeps the invalidate target hot).
  useInstallation();

  return null;
}
