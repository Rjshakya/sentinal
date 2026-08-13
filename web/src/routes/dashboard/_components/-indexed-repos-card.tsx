import { Link } from "@tanstack/react-router";
import { IconArrowRight } from "@tabler/icons-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
        <div className="grid gap-2 p-1.5 ring-1 ring-foreground/10">
          <Card className="bg-accent dark:bg-card">
            <CardHeader>
              <Skeleton className="h-4 w-full" />
            </CardHeader>
            <CardContent className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-2 p-1.5 ring-1 ring-foreground/10">
        <CardHeader>
          <CardTitle className=" flex items-center gap-2">Repositories</CardTitle>

          <CardDescription>
            Run a semantic search over the code Sentinel has indexed.
          </CardDescription>
        </CardHeader>
        <Card className="bg-accent dark:bg-card">
          <CardContent className=" p-2 ">
            {indexed.length === 0 ? (
              <p className="text-muted-foreground text-xs">
                No indexed repositories yet. Configure and index a repository from the Repositories
                page.
              </p>
            ) : (
              <ul className="divide-y rounded-md ">
                {indexed.map((repo) => {
                  const href = "/dashboard/search/$owner/$name" as const;
                  const params = { owner: repo.repo_owner, name: repo.repo_name } as const;
                  return (
                    <li key={repo.id} className="flex items-center justify-between gap-3 p-2">
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
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
