### web/src/routes/dashboard/_components/-indexed-repos-card.tsx

```diff

index 1e74cf4..aec4650 100644
--- a/web/src/routes/dashboard/_components/-indexed-repos-card.tsx
+++ b/web/src/routes/dashboard/_components/-indexed-repos-card.tsx
@@ -1,87 +1,99 @@
    2     2  import { Link } from "@tanstack/react-router";
    3       -import { IconArrowRight } from "@tabler/icons-react";
          3 +import { IconDatabase, IconLock, IconSearch } from "@tabler/icons-react";
    4     4  
          5 +import { Badge } from "@/components/ui/badge";
    5     6  import { Button } from "@/components/ui/button";
    6       -import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
          7 +import {
          8 +  Card,
          9 +  CardContent,
         10 +  CardDescription,
         11 +  CardHeader,
         12 +  CardTitle,
         13 +} from "@/components/ui/card";
    7    14  import { Skeleton } from "@/components/ui/skeleton";
    8    15  import { useUserRepos } from "@/lib/repos";
    9    16  
   10    17  export function IndexedReposCard() {
   11    18    const { data: repos, isLoading } = useUserRepos();
   12    19  
   13       -  const indexed = repos ?? [];
         20 +  const indexed = (repos ?? []).filter((r) => r.is_indexed);
   14    21  
   15    22    if (isLoading) {
   16    23      return (
   17       -      <div className="flex flex-col gap-4">
   18       -        <div className="flex items-center gap-2">
   19       -          <CardTitle className="text-lg">Indexed repositories</CardTitle>
   20       -        </div>
   21       -        <div className="grid gap-2 p-1.5 ring-1 ring-foreground/10">
   22       -          <Card className="bg-accent dark:bg-card">
   23       -            <CardHeader>
   24       -              <Skeleton className="h-4 w-full" />
   25       -            </CardHeader>
   26       -            <CardContent className="space-y-2">
   27       -              <Skeleton className="h-12 w-full" />
   28       -              <Skeleton className="h-12 w-full" />
   29       -            </CardContent>
   30       -          </Card>
   31       -        </div>
   32       -      </div>
         24 +      <Card>
         25 +        <CardHeader>
         26 +          <Skeleton className="h-5 w-40" />
         27 +          <Skeleton className="h-4 w-full" />
         28 +        </CardHeader>
         29 +        <CardContent className="space-y-2">
         30 +          <Skeleton className="h-12 w-full" />
         31 +          <Skeleton className="h-12 w-full" />
         32 +        </CardContent>
         33 +      </Card>
   33    34      );
   34    35    }
   35    36  
   36    37    return (
   37       -    <div className="flex flex-col gap-4">
   38       -      <div className="grid gap-2 p-1.5 ring-1 ring-foreground/10">
   39       -        <CardHeader>
   40       -          <CardTitle className=" flex items-center gap-2">Repositories</CardTitle>
   41       -
   42       -          <CardDescription>
   43       -            Run a semantic search over the code Sentinel has indexed.
   44       -          </CardDescription>
   45       -        </CardHeader>
   46       -        <Card className="bg-accent dark:bg-card py-0  ">
   47       -          <CardContent className=" p-0 ">
   48       -            {indexed.length === 0 ? (
   49       -              <p className="text-muted-foreground text-xs">
   50       -                No indexed repositories yet. Configure and index a repository from the Repositories
   51       -                page.
   52       -              </p>
   53       -            ) : (
   54       -              <ul className="divide-y rounded-md ">
   55       -                {indexed.map((repo) => {
   56       -                  const href = "/dashboard/search/$owner/$name" as const;
   57       -                  const params = { owner: repo.repo_owner, name: repo.repo_name } as const;
   58       -                  return (
   59       -                    <li
   60       -                      key={repo.id}
   61       -                      className="flex items-center justify-between gap-3 p-4 hover:bg-background/50   dark:hover:bg-background/40 transition-colors ease-in-out duration-300  "
   62       -                    >
   63       -                      <div className="min-w-0 flex-1 space-y-1">
   64       -                        <div className="flex flex-wrap items-center gap-2">
   65       -                          <span className="truncate font-medium">
   66       -                            {repo.repo_owner}/{repo.repo_name}
   67       -                          </span>
   68       -                        </div>
   69       -                      </div>
   70       -                      <Button
   71       -                        size="icon-sm"
   72       -                        variant="ghost"
   73       -                        className="gap-1"
   74       -                        render={<Link to={href} params={params} />}
         38 +    <Card>
         39 +      <CardHeader>
         40 +        <CardTitle className="flex items-center gap-2">
         41 +          <IconDatabase className="size-4" />
         42 +          Indexed repositories
         43 +        </CardTitle>
         44 +        <CardDescription>
         45 +          Run a semantic search over the code Sentinel has indexed.
         46 +        </CardDescription>
         47 +      </CardHeader>
         48 +      <CardContent className="space-y-2">
         49 +        {indexed.length === 0 ? (
         50 +          <p className="text-muted-foreground text-xs">
         51 +            No indexed repositories yet. Configure and index a repository from the Repositories page.
         52 +          </p>
         53 +        ) : (
         54 +          <ul className="divide-y rounded-md border">
         55 +            {indexed.map((repo) => {
         56 +              const href = "/dashboard/search/$owner/$name" as const;
         57 +              const params = { owner: repo.repo_owner, name: repo.repo_name } as const;
         58 +              return (
         59 +                <li
         60 +                  key={repo.id}
         61 +                  className="flex items-center justify-between gap-3 p-3"
         62 +                >
         63 +                  <div className="min-w-0 flex-1 space-y-1">
         64 +                    <div className="flex flex-wrap items-center gap-2">
         65 +                      <span className="truncate font-medium">
         66 +                        {repo.repo_owner}/{repo.repo_name}
         67 +                      </span>
         68 +                      {repo.private && (
         69 +                        <Badge variant="outline" className="gap-1">
         70 +                          <IconLock className="size-3" />
         71 +                          Private
         72 +                        </Badge>
         73 +                      )}
         74 +                      <Badge
         75 +                        variant="default"
         76 +                        className="gap-1 border-sky-600/40 bg-sky-600/15 text-sky-700 dark:text-sky-300"
   75    77                        >
   76       -                        <IconArrowRight className="size-4" />
   77       -                      </Button>
   78       -                    </li>
   79       -                  );
   80       -                })}
   81       -              </ul>
   82       -            )}
   83       -          </CardContent>
   84       -        </Card>
   85       -      </div>
   86       -    </div>
         78 +                        <IconDatabase className="size-3" />
         79 +                        Indexed
         80 +                      </Badge>
         81 +                    </div>
         82 +                  </div>
         83 +                  <Button
         84 +                    size="sm"
         85 +                    variant="outline"
         86 +                    className="gap-1"
         87 +                    render={<Link to={href} params={params} />}
         88 +                  >
         89 +                    <IconSearch className="size-3.5" />
         90 +                    Search
         91 +                  </Button>
         92 +                </li>
         93 +              );
         94 +            })}
         95 +          </ul>
         96 +        )}
         97 +      </CardContent>
         98 +    </Card>
   87    99    );
   88   100  }

```
