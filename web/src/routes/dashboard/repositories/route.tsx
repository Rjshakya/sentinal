import { GithubConnectionCard } from "@/routes/dashboard/_components/-github-connection-card";
import { RepoList } from "@/routes/dashboard/repositories/_components/-repo-list";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { protectPage } from "@/lib/auth";
import type { SetupRepo } from "@/lib/api";
import { useInstallation } from "@/lib/installation";
import { useRepos, useSetup } from "@/lib/repos";
import { useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";

export const Route = createFileRoute("/dashboard/repositories")({
  component: RepositoriesPage,
  beforeLoad: protectPage,
  ssr: false,
});

/**
 * Delay before re-fetching the GitHub repos list after Configure.
 * The DBOS workflow's first step (``ensure_repo_and_sandbox_step``)
 * upserts the local ``Repo`` row synchronously, so by the time the
 * POST 202 returns + this delay elapses, the row exists and the
 * next fetch will mark the repo as ``is_configured: true``.
 */
const REFETCH_AFTER_CONFIGURE_MS = 5_000;

function RepositoriesPage() {
  const { data: installation, isLoading: installationLoading } = useInstallation();
  const isConnected = !!installation?.connected;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Repositories</h1>
        <p className="text-muted-foreground mt-1 text-sm">Select the repositories to configure.</p>
      </div>

      {installationLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : !isConnected ? (
        <GithubConnectionCard />
      ) : (
        <ConnectedView />
      )}
    </div>
  );
}

function ConnectedView() {
  const { data: repos, isLoading, isError, refetch } = useRepos();
  const setup = useSetup();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const selectedPayload = useMemo<SetupRepo[]>(() => {
    if (!repos) return [];
    return Array.from(selected)
      .map((fullName) => repos.find((r) => r.full_name === fullName))
      .filter((r): r is NonNullable<typeof r> => r !== undefined)
      .map((r) => ({
        id: r.id,
        owner: r.owner,
        name: r.name,
        installation_id: r.installation_id,
      }));
  }, [repos, selected]);

  // ``selected`` is constrained at the source: the RepoList
  // disables the checkbox on configured rows, so ``handleToggle``
  // is never called for them. No reconciliation needed.
  function handleToggle(fullName: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(fullName)) {
        next.delete(fullName);
      } else {
        next.add(fullName);
      }
      return next;
    });
  }

  function handleConfigure() {
    if (selectedPayload.length === 0) return;
    setup.mutate(selectedPayload, {
      onSuccess: (data) => {
        const ok = data.results.filter((r) => r.setup.ok).length;
        const failed = data.results.length - ok;
        setSelected(new Set());
        if (failed === 0) {
          toast.success(`Configured ${ok} ${ok === 1 ? "repo" : "repos"}`);
        } else {
          toast.warning(`Configured ${ok}, ${failed} failed`);
        }
        // Re-fetch the GitHub repos list so the just-configured
        // repos show up as ``isConfigured`` on the next paint.
        // The DBOS workflow's first step writes the local Repo row
        // synchronously; the delay gives that step time to land
        // before we re-query. The cache is process-global so we
        // don't need to track the timer across unmounts.
        window.setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ["github", "repos"] });
        }, REFETCH_AFTER_CONFIGURE_MS);
      },
      onError: (err) => {
        toast.error(err.message);
      },
    });
  }

  const allConfigured = !!repos && repos.length > 0 && repos.every((r) => r.is_configured);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">Failed to load GitHub repositories.</p>
        <Button variant="outline" className="mt-3" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (!repos || repos.length === 0) {
    return (
      <div className="space-y-4">
        <GithubConnectionCard />
        <div className="rounded-lg border p-6 text-center">
          <p className="text-muted-foreground text-sm">
            No repositories found. Grant Sentinel access to repos on GitHub to see them here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <RepoList repos={repos} selected={selected} onToggle={handleToggle} />
      {allConfigured ? (
        <p className="text-muted-foreground text-sm">All repositories are already configured.</p>
      ) : (
        <div className="flex items-center justify-between border-t pt-4">
          <p className="text-muted-foreground text-sm">{selected.size} selected</p>
          <Button
            disabled={selectedPayload.length === 0 || setup.isPending}
            onClick={handleConfigure}
          >
            {setup.isPending ? "Configuring..." : "Configure"}
          </Button>
        </div>
      )}
    </div>
  );
}
