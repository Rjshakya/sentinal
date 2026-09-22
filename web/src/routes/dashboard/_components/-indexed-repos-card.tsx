import { Link } from "@tanstack/react-router";
import { IconArrowRight } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { CommonCard } from "@/components/common-card";
import { CardDescription, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useUserRepos } from "@/lib/repos";

export function IndexedReposCard() {
  const { data: repos, isLoading } = useUserRepos();

  const indexed = repos ?? [];

  if (isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <CardTitle className="text-lg">Indexed repositories</CardTitle>
        </div>
        <CommonCard
          header={<Skeleton className="h-4 w-full" />}
          body={
            <>
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </>
          }
          bodyClassName="space-y-2"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <CommonCard
        cardClassName="py-0"
        header={
          <div className="grid gap-0.5">
            <CardTitle className="flex items-center gap-2">Repositories</CardTitle>
            <CardDescription>
              Run a semantic search over the code Sentinel has indexed.
            </CardDescription>
          </div>
        }
        bodyClassName="p-0"
        body={
          indexed.length === 0 ? (
            <p className="text-muted-foreground text-xs">
              No indexed repositories yet. Configure and index a repository from the Repositories
              page.
            </p>
          ) : (
            <ul className="divide-y rounded-md">
              {indexed.map((repo) => {
                const href = "/dashboard/search/$owner/$name" as const;
                const params = { owner: repo.repo_owner, name: repo.repo_name } as const;
                return (
                  <li
                    key={repo.id}
                    className="flex items-center justify-between gap-3 p-4 transition-colors duration-300 ease-in-out hover:bg-background/50 dark:hover:bg-background/40"
                  >
                    <div className="min-w-0 flex-1 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="truncate font-medium">
                          {repo.repo_owner}/{repo.repo_name}
                        </span>
                      </div>
                    </div>
                    <Button
                      size="icon-sm"
                      variant="ghost"
                      className="gap-1"
                      render={<Link to={href} params={params} />}
                    >
                      <IconArrowRight className="size-4" />
                    </Button>
                  </li>
                );
              })}
            </ul>
          )
        }
      />
    </div>
  );
}
