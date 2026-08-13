import { Link } from "@tanstack/react-router";
import { IconDatabase, IconLock, IconSearch } from "@tabler/icons-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useUserRepos } from "@/lib/repos";

export function IndexedReposCard() {
  const { data: repos, isLoading } = useUserRepos();

  const indexed = (repos ?? []).filter((r) => r.is_indexed);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-full" />
        </CardHeader>
        <CardContent className="space-y-2">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <IconDatabase className="size-4" />
          Indexed repositories
        </CardTitle>
        <CardDescription>
          Run a semantic search over the code Sentinel has indexed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {indexed.length === 0 ? (
          <p className="text-muted-foreground text-xs">
            No indexed repositories yet. Configure and index a repository from the Repositories page.
          </p>
        ) : (
          <ul className="divide-y rounded-md border">
            {indexed.map((repo) => {
              const href = "/dashboard/search/$owner/$name" as const;
              const params = { owner: repo.repo_owner, name: repo.repo_name } as const;
              return (
                <li
                  key={repo.id}
                  className="flex items-center justify-between gap-3 p-3"
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate font-medium">
                        {repo.repo_owner}/{repo.repo_name}
                      </span>
                      {repo.private && (
                        <Badge variant="outline" className="gap-1">
                          <IconLock className="size-3" />
                          Private
                        </Badge>
                      )}
                      <Badge
                        variant="default"
                        className="gap-1 border-sky-600/40 bg-sky-600/15 text-sky-700 dark:text-sky-300"
                      >
                        <IconDatabase className="size-3" />
                        Indexed
                      </Badge>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1"
                    render={<Link to={href} params={params} />}
                  >
                    <IconSearch className="size-3.5" />
                    Search
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
