import { GithubConnectionCard } from "@/routes/dashboard/_components/-github-connection-card";
import { RepoList } from "@/routes/dashboard/repositories/_components/-repo-list";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { protectPage } from "@/lib/auth";
import type { Repo, SetupRepo } from "@/lib/api";
import { useIndexRepo } from "@/lib/indexing";
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

function RepositoriesPage() {
  const { data: installation, isLoading: installationLoading } = useInstallation();
  const isConnected = !!installation?.connected;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
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
  const indexRepo = useIndexRepo();
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
        default_branch: r.default_branch,
      }));
  }, [repos, selected]);

  const sortedRepos = useMemo(() => {
    if (!repos) return [];
    return [...repos].sort((a, b) => {
      const aConfigured = a.is_configured ? 0 : 1;
      const bConfigured = b.is_configured ? 0 : 1;
      if (aConfigured !== bConfigured) return aConfigured - bConfigured;

      const aHasLang = a.language ? 0 : 1;
      const bHasLang = b.language ? 0 : 1;
      if (aHasLang !== bHasLang) return aHasLang - bHasLang;

      const aHasDesc = a.description ? 0 : 1;
      const bHasDesc = b.description ? 0 : 1;
      return aHasDesc - bHasDesc;
    });
  }, [repos]);

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
        queryClient.invalidateQueries({ queryKey: ["github", "repos"] });
      },
      onError: (err) => {
        toast.error(err.message);
      },
    });
  }

  function handleIndex(repo: Repo) {
    indexRepo.mutate(
      {
        repo_owner: repo.owner,
        repo_name: repo.name,
        repo_url: repo.clone_url,
        default_branch: repo.default_branch,
      },
      {
        onSuccess: () => {
          toast.success(`Indexing ${repo.full_name}`);
          queryClient.invalidateQueries({ queryKey: ["github", "repos"] });
        },
        onError: (err) => {
          toast.error(err.message);
        },
      },
    );
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
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div className="">
          <h1 className="text-2xl font-semibold tracking-tight">Repositories</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Select the repositories to configure.
          </p>
        </div>

        <div className="">
          {allConfigured ? (
            <p className="text-muted-foreground text-sm">
              All repositories are already configured.
            </p>
          ) : (
            <div className="">
              <Button
                disabled={selectedPayload.length === 0 || setup.isPending}
                onClick={handleConfigure}
              >
                {allConfigured
                  ? "All Configured"
                  : setup.isPending
                    ? "Configuring..."
                    : "Configure"}
                {selected.size > 0 && <p>{selected.size} </p>}
              </Button>
            </div>
          )}
        </div>
      </div>

      <RepoList
        repos={sortedRepos}
        selected={selected}
        onToggle={handleToggle}
        onIndex={handleIndex}
      />
    </div>
  );
}
