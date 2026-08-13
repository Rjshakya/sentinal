import { ActionsCard } from "@/routes/dashboard/_components/-actions-card";
import { GreetingCard } from "@/routes/dashboard/_components/-greeting-card";
import { IndexedReposCard } from "@/routes/dashboard/_components/-indexed-repos-card";
import { StatCard } from "@/routes/dashboard/_components/-stat-card";
import { protectPage } from "@/lib/auth";
import { useInstallation } from "@/lib/installation";
import { useUserStats } from "@/lib/stats";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { IconAlertTriangle, IconClipboardCheck, IconMessage2 } from "@tabler/icons-react";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

export const Route = createFileRoute("/dashboard/")({
  component: DashboardOverview,
  beforeLoad: protectPage,
  ssr: false,
});

function DashboardOverview() {
  const { data: stats, isLoading: statsLoading } = useUserStats();

  return (
    <div className="flex flex-1 flex-col gap-8  p-4 pt-0 max-w-3xl mx-auto w-full ">
      <GreetingCard />
      <div className="grid gap-2 md:grid-cols-3">
        <StatCard
          label="PRs reviewed"
          value={stats?.prs_reviewed}
          loading={statsLoading}
          icon={<IconClipboardCheck className="text-muted-foreground size-4  " />}
        />
        <StatCard
          label="Comments issued"
          value={stats?.comments_issued}
          loading={statsLoading}
          icon={<IconMessage2 className="text-muted-foreground size-4" />}
        />
        <StatCard
          label="Bugs caught"
          value={stats?.bugs_caught}
          loading={statsLoading}
          icon={<IconAlertTriangle className="text-muted-foreground size-4" />}
        />
      </div>
      <IndexedReposCard />
      <ActionsCard />
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
