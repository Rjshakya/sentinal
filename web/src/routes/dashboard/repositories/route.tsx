import { GithubConnectionCard } from "@/routes/dashboard/_components/-github-connection-card";
import { CodeSearch } from "@/routes/dashboard/repositories/_components/-code-search";
import { RepoList } from "@/routes/dashboard/repositories/_components/-repo-list";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { protectPage } from "@/lib/auth";
import { getGithubConnection, useConnections } from "@/lib/connections";
import type { IndexingRepo } from "@/lib/api";
import { useRepos, useStartIndexing, useUserRepos } from "@/lib/repos";
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { toast } from "sonner";

export const Route = createFileRoute("/dashboard/repositories")({
  component: RepositoriesPage,
  beforeLoad: protectPage,
  ssr: false,
});

function RepositoriesPage() {
  const { data: connections } = useConnections();
  const github = getGithubConnection(connections);
  const isConnected = !!github?.connected;

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Repositories</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Select the repositories to enable AI-powered code reviews on.
        </p>
      </div>

      {!isConnected ? <GithubConnectionCard /> : <ConnectedView />}
    </div>
  );
}

function ConnectedView() {
  const { data: repos, isLoading, isError, refetch } = useRepos();
  const { data: userRepos } = useUserRepos();
  const startIndexing = useStartIndexing();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const indexedIds = useMemo<Set<string>>(() => {
    if (!userRepos) return new Set();
    return new Set(userRepos.map((r) => r.id));
  }, [userRepos]);

  const selectedPayload = useMemo<IndexingRepo[]>(() => {
    if (!repos) return [];
    return Array.from(selected)
      .map((fullName) => repos.find((r) => r.full_name === fullName))
      .filter((r): r is NonNullable<typeof r> => r !== undefined)
      .filter((r) => !indexedIds.has(String(r.id)))
      .map((r) => ({
        id: r.id.toString(),
        name: r.name,
        full_name: r.full_name,
        html_url: r.html_url,
        private: r.private,
        default_branch: r.default_branch,
        clone_url: r.html_url,
        owner: r.owner,
      }));
  }, [repos, selected, indexedIds]);

  const indexableCount = useMemo(() => {
    if (!repos) return 0;
    return repos.filter((r) => !indexedIds.has(String(r.id))).length;
  }, [repos, indexedIds]);

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

  function handleStart() {
    if (selectedPayload.length === 0) return;
    startIndexing.mutate(selectedPayload, {
      onSuccess: (data) => {
        toast.success(`Indexing started for ${data.accepted} repos`);
        setSelected(new Set());
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
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">
          No repositories found on this GitHub account.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {userRepos && userRepos.length > 0 && <CodeSearch repos={userRepos} />}
      <RepoList repos={repos} selected={selected} onToggle={handleToggle} indexed={indexedIds} />
      <div className="flex items-center justify-between border-t pt-4">
        <p className="text-muted-foreground text-sm">
          {selected.size} selected
          {indexedIds.size > 0 ? ` · ${indexedIds.size} already indexed` : ""}
        </p>
        <Button
          disabled={selectedPayload.length === 0 || startIndexing.isPending}
          onClick={handleStart}
        >
          {startIndexing.isPending ? "Starting..." : "Start indexing"}
        </Button>
      </div>
      {indexableCount === 0 && (
        <p className="text-muted-foreground text-center text-sm">
          All your repositories are already indexed.
        </p>
      )}
    </div>
  );
}
