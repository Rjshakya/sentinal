import { createFileRoute, Link } from "@tanstack/react-router";
import {
  IconArrowLeft,
  IconDatabase,
  IconLock,
  IconSearch,
  IconX,
} from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { protectPage } from "@/lib/auth";
import type { CodeSearchResult } from "@/lib/api";
import { useCodeSearch } from "@/lib/search";
import { useUserRepos } from "@/lib/repos";

export const Route = createFileRoute("/dashboard/search/$owner/$name")({
  component: SearchPage,
  beforeLoad: protectPage,
  ssr: false,
});

function SearchPage() {
  const { owner, name } = Route.useParams();
  const [query, setQuery] = useState("");
  const search = useCodeSearch();
  const { data: repos } = useUserRepos();

  const repo = useMemo(
    () =>
      (repos ?? []).find(
        (r) => r.repo_owner === owner && r.repo_name === name,
      ),
    [repos, owner, name],
  );

  const canSearch = query.trim().length > 0 && !search.isPending;

  const sortedResults = useMemo(
    () =>
      [...(search.data?.results ?? [])].sort(
        (a, b) => (b._relevance_score ?? 0) - (a._relevance_score ?? 0),
      ),
    [search.data],
  );

  // Surface non-401 errors as toasts. The apiClient throws ApiError on
  // every non-2xx; the message body carries the typed backend detail
  // (e.g. "repo is not installed for this user").
  useEffect(() => {
    if (search.isError) {
      toast.error(search.error.message);
    }
  }, [search.isError, search.error]);

  function handleSearch() {
    if (!canSearch) return;
    search.mutate({ owner, repo: name, query: query.trim(), limit: 20 });
  }

  function handleReset() {
    setQuery("");
    search.reset();
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2 gap-1 text-muted-foreground"
            render={<Link to="/dashboard" />}
          >
            <IconArrowLeft className="size-3.5" />
            Dashboard
          </Button>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            {owner}/{name}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {repo?.private && (
              <Badge variant="outline" className="gap-1">
                <IconLock className="size-3" />
                Private
              </Badge>
            )}
            {repo?.is_indexed ? (
              <Badge
                variant="default"
                className="gap-1 border-sky-600/40 bg-sky-600/15 text-sky-700 dark:text-sky-300"
              >
                <IconDatabase className="size-3" />
                Indexed
              </Badge>
            ) : (
              <Badge variant="outline" className="gap-1">
                Not indexed
              </Badge>
            )}
          </div>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <IconSearch className="size-4" />
            Search code
          </CardTitle>
          <CardDescription>
            Hybrid FTS + vector search across the indexed chunks of {owner}/{name}.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="e.g. how does auth middleware attach the session?"
              onKeyDown={(event) => {
                if (event.key === "Enter") handleSearch();
              }}
            />
            <Button onClick={handleSearch} disabled={!canSearch} size="sm" className="gap-1">
              <IconSearch className="size-3.5" />
              Search
            </Button>
            {(search.data || search.isError) && (
              <Button onClick={handleReset} size="sm" variant="ghost" className="gap-1">
                <IconX className="size-3.5" />
                Clear
              </Button>
            )}
          </div>

          <Separator />

          {search.isPending && <SearchSkeleton />}
          {search.data && !search.isPending && (
            <SearchResults
              results={sortedResults}
              query={search.data.query ?? query.trim()}
              owner={owner}
              repo={name}
            />
          )}
          {!search.data && !search.isPending && !search.isError && (
            <p className="text-muted-foreground text-xs">
              Enter a query to search this repository&apos;s indexed code.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SearchResults({
  results,
  query,
  owner,
  repo,
}: {
  results: CodeSearchResult[];
  query: string;
  owner: string;
  repo: string;
}) {
  if (results.length === 0) {
    return (
      <p className="text-muted-foreground text-xs">
        No matches for &ldquo;{query}&rdquo; in {owner}/{repo}.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">
        {results.length} match{results.length === 1 ? "" : "es"} for &ldquo;{query}&rdquo;
      </p>
      <ScrollArea className="max-h-[28rem] overflow-y-auto">
        <ul className="divide-y rounded-md border">
          {results.map((result, idx) => (
            <li
              key={`${result.file_name}-${result.start_line}-${idx}`}
              className="space-y-2 p-3"
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate font-medium">{result.file_name}</span>
                <Badge variant="outline" className="font-mono">
                  L{result.start_line}-{result.end_line}
                </Badge>
                {result.language && (
                  <Badge variant="secondary">{result.language}</Badge>
                )}
                {result.node_types.length > 0 && (
                  <Badge variant="secondary">{result.node_types.join(" · ")}</Badge>
                )}
              </div>
              <pre className="bg-muted/40 overflow-x-auto rounded-md p-2 text-xs leading-relaxed">
                <code>{result.content}</code>
              </pre>
            </li>
          ))}
        </ul>
      </ScrollArea>
    </div>
  );
}

function SearchSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="space-y-2 rounded-md border p-3">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
        </div>
      ))}
    </div>
  );
}
