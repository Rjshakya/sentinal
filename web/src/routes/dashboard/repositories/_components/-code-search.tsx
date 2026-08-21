import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import type { CodeSearchResult, UserRepo } from "@/lib/api";
import { useCodeSearch } from "@/lib/search";
import { IconSearch, IconX } from "@tabler/icons-react";
import { useMemo, useState } from "react";

type Props = {
  repos: UserRepo[];
};

export function CodeSearch({ repos }: Props) {
  const [repoId, setRepoId] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  const search = useCodeSearch();

  const selectedRepo = repos.find((r) => r.id === repoId);
  const canSearch = !!selectedRepo && query.trim().length > 0 && !search.isPending;

  const sortedResults = useMemo(
    () =>
      [...(search.data?.results ?? [])].sort(
        (a, b) => (b._relevance_score ?? 0) - (a._relevance_score ?? 0),
      ),
    [search.data],
  );

  function handleSearch() {
    if (!selectedRepo || !canSearch) return;
    search.mutate(
      {
        owner: selectedRepo.repo_owner,
        repo: selectedRepo.repo_name,
        query: query.trim(),
      },
      {
        onError: (err) => {
          // Toast handled by the parent; surfacing here keeps errors local.
          console.error("code search failed", err);
        },
      },
    );
  }

  function handleReset() {
    setRepoId("");
    setQuery("");
    search.reset();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <IconSearch className="size-4" />
          Search code
        </CardTitle>
        <CardDescription>Run a semantic query against the indexed repositories.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Select value={repoId} onValueChange={(v) => setRepoId(v ?? "")}>
            <SelectTrigger className="sm:w-64">
              <SelectValue placeholder="Select a repository" />
            </SelectTrigger>
            <SelectContent>
              {repos.map((r) => (
                <SelectItem key={r.id} value={r.id}>
                  {r.repo_owner}/{r.repo_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="flex flex-1 items-center gap-2">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. how does auth middleware attach the session?"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch();
              }}
              disabled={!selectedRepo}
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
        </div>

        <Separator />

        {search.isPending && <SearchSkeleton />}
        {search.isError && <p className="text-destructive text-xs">{search.error.message}</p>}
        {search.data && !search.isPending && (
          <SearchResults
            results={sortedResults}
            query={search.data.query ?? query}
            repoName={search.data.repo ?? selectedRepo?.repo_name ?? ""}
          />
        )}
        {!search.data && !search.isPending && !search.isError && (
          <p className="text-muted-foreground text-xs">
            Pick a repository and enter a query to search its indexed code.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function asNodeTypes(value: string | string[] | null | undefined): string[] {
  if (value == null) return [];
  if (Array.isArray(value)) return value;
  return value
    .split(";")
    .map((s) => s.trim())
    .filter(Boolean);
}

function SearchResults({
  results,
  query,
  repoName,
}: {
  results: CodeSearchResult[];
  query: string;
  repoName: string;
}) {
  if (results.length === 0) {
    return (
      <p className="text-muted-foreground text-xs">
        No matches for &ldquo;{query}&rdquo; in {repoName}.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">
        {results.length} match{results.length === 1 ? "" : "es"} for &ldquo;{query}&rdquo;
      </p>
      <ScrollArea className="max-h-96 overflow-y-auto ">
        <ul className="divide-y rounded-md border  ">
          {results.map((r, idx) => {
            const tags = asNodeTypes(r.node_types);
            return (
              <li key={`${r.file_name ?? "result"}-${idx}`} className="space-y-2 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate font-medium">{r.file_name ?? "unknown file"}</span>
                  {(r.start_line != null || r.end_line != null) && (
                    <Badge variant="outline" className="font-mono">
                      L{r.start_line ?? "?"}-{r.end_line ?? "?"}
                    </Badge>
                  )}
                  {r.language && <Badge variant="secondary">{r.language}</Badge>}
                  {tags.length > 0 && <Badge variant="secondary">{tags.join(" · ")}</Badge>}
                </div>
                {r.content && (
                  <pre className="bg-muted/40 overflow-x-auto rounded-md p-2 text-xs leading-relaxed">
                    <code>{r.content}</code>
                  </pre>
                )}
              </li>
            );
          })}
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
