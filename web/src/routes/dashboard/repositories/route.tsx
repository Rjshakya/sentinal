import { GithubConnectionCard } from "@/routes/dashboard/_components/-github-connection-card";
import { RepoList } from "@/routes/dashboard/repositories/_components/-repo-list";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { protectPage } from "@/lib/auth";
import type { SetupRepo } from "@/lib/api";
import { useInstallation } from "@/lib/installation";
import { useRepos, useSetup } from "@/lib/repos";
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";

export const Route = createFileRoute("/dashboard/repositories")({
  component: RepositoriesPage,
  beforeLoad: protectPage,
  ssr: false,
});

function RepositoriesPage() {
  const { data: installation, isLoading: installationLoading } = useInstallation();
  const isConnected = !!installation?.connected;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Repositories</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Select the repositories to configure.
        </p>
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
          toast.success(
            `Configured ${ok} ${ok === 1 ? "repo" : "repos"}`,
          );
        } else {
          toast.warning(`Configured ${ok}, ${failed} failed`);
        }
      },
      onError: (err) => {
        toast.error(err.message);
      },
    });
  }

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
            No repositories found. Grant Sentinel access to repos on GitHub to see
            them here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <RepoList repos={repos} selected={selected} onToggle={handleToggle} />
      <div className="flex items-center justify-between border-t pt-4">
        <p className="text-muted-foreground text-sm">{selected.size} selected</p>
        <Button
          disabled={selectedPayload.length === 0 || setup.isPending}
          onClick={handleConfigure}
        >
          {setup.isPending ? "Configuring..." : "Configure"}
        </Button>
      </div>
    </div>
  );
}
