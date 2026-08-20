### web/src/routes/dashboard/search/$owner/$name/route.tsx

```diff

index e304a3e..9425a45 100644
--- a/web/src/routes/dashboard/search/$owner/$name/route.tsx
+++ b/web/src/routes/dashboard/search/$owner/$name/route.tsx
@@ -1,14 +1,31 @@
    2     2  import { createFileRoute, Link } from "@tanstack/react-router";
    3       -import { IconArrowLeft } from "@tabler/icons-react";
    4       -import { useState } from "react";
          3 +import {
          4 +  IconArrowLeft,
          5 +  IconDatabase,
          6 +  IconLock,
          7 +  IconSearch,
          8 +  IconX,
          9 +} from "@tabler/icons-react";
         10 +import { useEffect, useMemo, useState } from "react";
         11 +import { toast } from "sonner";
    5    12  
         13 +import { Badge } from "@/components/ui/badge";
    6    14  import { Button } from "@/components/ui/button";
    7       -import { Card, CardContent, CardHeader } from "@/components/ui/card";
         15 +import {
         16 +  Card,
         17 +  CardContent,
         18 +  CardDescription,
         19 +  CardHeader,
         20 +  CardTitle,
         21 +} from "@/components/ui/card";
    8    22  import { Input } from "@/components/ui/input";
         23 +import { ScrollArea } from "@/components/ui/scroll-area";
         24 +import { Separator } from "@/components/ui/separator";
    9    25  import { Skeleton } from "@/components/ui/skeleton";
   10    26  import { protectPage } from "@/lib/auth";
         27 +import type { CodeSearchResult } from "@/lib/api";
   11    28  import { useCodeSearch } from "@/lib/search";
   12       -import { SearchResults } from "./-components/search-results";
         29 +import { useUserRepos } from "@/lib/repos";
   13    30  
   14    31  export const Route = createFileRoute("/dashboard/search/$owner/$name")({
   15    32    component: SearchPage,
@@ -20,40 +37,127 @@ function SearchPage() {
   21    38    const { owner, name } = Route.useParams();
   22    39    const [query, setQuery] = useState("");
   23    40    const search = useCodeSearch();
         41 +  const { data: repos } = useUserRepos();
         42 +
         43 +  const repo = useMemo(
         44 +    () =>
         45 +      (repos ?? []).find(
         46 +        (r) => r.repo_owner === owner && r.repo_name === name,
         47 +      ),
         48 +    [repos, owner, name],
         49 +  );
         50 +
         51 +  const canSearch = query.trim().length > 0 && !search.isPending;
         52 +
         53 +  const sortedResults = useMemo(
         54 +    () =>
         55 +      [...(search.data?.results ?? [])].sort(
         56 +        (a, b) => (b._relevance_score ?? 0) - (a._relevance_score ?? 0),
         57 +      ),
         58 +    [search.data],
         59 +  );
         60 +
         61 +  // Surface non-401 errors as toasts. The apiClient throws ApiError on
         62 +  // every non-2xx; the message body carries the typed backend detail
         63 +  // (e.g. "repo is not installed for this user").
         64 +  useEffect(() => {
         65 +    if (search.isError) {
         66 +      toast.error(search.error.message);
         67 +    }
         68 +  }, [search.isError, search.error]);
   24    69  
   25    70    function handleSearch() {
   26       -    if (query.trim().length <= 0 && !search.isPending) return;
         71 +    if (!canSearch) return;
   27    72      search.mutate({ owner, repo: name, query: query.trim(), limit: 20 });
   28    73    }
   29    74  
         75 +  function handleReset() {
         76 +    setQuery("");
         77 +    search.reset();
         78 +  }
         79 +
   30    80    return (
   31    81      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 p-6">
   32    82        <div className="flex items-center justify-between gap-3">
   33    83          <div className="min-w-0">
   34       -          <h1 className=" text-2xl font-semibold tracking-tight">
         84 +          <Button
         85 +            variant="ghost"
         86 +            size="sm"
         87 +            className="-ml-2 gap-1 text-muted-foreground"
         88 +            render={<Link to="/dashboard" />}
         89 +          >
         90 +            <IconArrowLeft className="size-3.5" />
         91 +            Dashboard
         92 +          </Button>
         93 +          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
   35    94              {owner}/{name}
   36    95            </h1>
         96 +          <div className="mt-1 flex flex-wrap items-center gap-2">
         97 +            {repo?.private && (
         98 +              <Badge variant="outline" className="gap-1">
         99 +                <IconLock className="size-3" />
        100 +                Private
        101 +              </Badge>
        102 +            )}
        103 +            {repo?.is_indexed ? (
        104 +              <Badge
        105 +                variant="default"
        106 +                className="gap-1 border-sky-600/40 bg-sky-600/15 text-sky-700 dark:text-sky-300"
        107 +              >
        108 +                <IconDatabase className="size-3" />
        109 +                Indexed
        110 +              </Badge>
        111 +            ) : (
        112 +              <Badge variant="outline" className="gap-1">
        113 +                Not indexed
        114 +              </Badge>
        115 +            )}
        116 +          </div>
   37   117          </div>
   38   118        </div>
   39   119  
   40       -      <Card className="py-0 pt-1 pb-1 px-1 bg-muted ">
   41       -        <CardHeader className="p-0  ">
        120 +      <Card>
        121 +        <CardHeader>
        122 +          <CardTitle className="flex items-center gap-2">
        123 +            <IconSearch className="size-4" />
        124 +            Search code
        125 +          </CardTitle>
        126 +          <CardDescription>
        127 +            Hybrid FTS + vector search across the indexed chunks of {owner}/{name}.
        128 +          </CardDescription>
        129 +        </CardHeader>
        130 +        <CardContent className="space-y-3">
   42   131            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
   43   132              <Input
   44       -              className=" bg-muted dark:bg-muted h-10  border-0 border-b  focus-visible:ring-0 focus-visible:border-b   px-1  "
   45   133                value={query}
   46       -              onChange={(e) => setQuery(e.currentTarget.value)}
        134 +              onChange={(event) => setQuery(event.target.value)}
   47   135                placeholder="e.g. how does auth middleware attach the session?"
   48       -              onKeyDown={(e) => {
   49       -                if (e.key === "Enter") handleSearch();
        136 +              onKeyDown={(event) => {
        137 +                if (event.key === "Enter") handleSearch();
   50   138                }}
   51   139              />
        140 +            <Button onClick={handleSearch} disabled={!canSearch} size="sm" className="gap-1">
        141 +              <IconSearch className="size-3.5" />
        142 +              Search
        143 +            </Button>
        144 +            {(search.data || search.isError) && (
        145 +              <Button onClick={handleReset} size="sm" variant="ghost" className="gap-1">
        146 +                <IconX className="size-3.5" />
        147 +                Clear
        148 +              </Button>
        149 +            )}
   52   150            </div>
   53       -        </CardHeader>
   54       -        <CardContent className={search?.data?.results?.length ? "px-0" : "p-2"}>
        151 +
        152 +          <Separator />
        153 +
   55   154            {search.isPending && <SearchSkeleton />}
   56   155            {search.data && !search.isPending && (
   57       -            <SearchResults results={search.data?.results || []} owner={owner} repo={name} />
        156 +            <SearchResults
        157 +              results={sortedResults}
        158 +              query={search.data.query ?? query.trim()}
        159 +              owner={owner}
        160 +              repo={name}
        161 +            />
   58   162            )}
   59   163            {!search.data && !search.isPending && !search.isError && (
   60   164              <p className="text-muted-foreground text-xs">
@@ -66,6 +170,60 @@ function SearchPage() {
   67   171    );
   68   172  }
   69   173  
        174 +function SearchResults({
        175 +  results,
        176 +  query,
        177 +  owner,
        178 +  repo,
        179 +}: {
        180 +  results: CodeSearchResult[];
        181 +  query: string;
        182 +  owner: string;
        183 +  repo: string;
        184 +}) {
        185 +  if (results.length === 0) {
        186 +    return (
        187 +      <p className="text-muted-foreground text-xs">
        188 +        No matches for &ldquo;{query}&rdquo; in {owner}/{repo}.
        189 +      </p>
        190 +    );
        191 +  }
        192 +
        193 +  return (
        194 +    <div className="space-y-2">
        195 +      <p className="text-muted-foreground text-xs">
        196 +        {results.length} match{results.length === 1 ? "" : "es"} for &ldquo;{query}&rdquo;
        197 +      </p>
        198 +      <ScrollArea className="max-h-[28rem] overflow-y-auto">
        199 +        <ul className="divide-y rounded-md border">
        200 +          {results.map((result, idx) => (
        201 +            <li
        202 +              key={`${result.file_name}-${result.start_line}-${idx}`}
        203 +              className="space-y-2 p-3"
        204 +            >
        205 +              <div className="flex flex-wrap items-center gap-2">
        206 +                <span className="truncate font-medium">{result.file_name}</span>
        207 +                <Badge variant="outline" className="font-mono">
        208 +                  L{result.start_line}-{result.end_line}
        209 +                </Badge>
        210 +                {result.language && (
        211 +                  <Badge variant="secondary">{result.language}</Badge>
        212 +                )}
        213 +                {result.node_types.length > 0 && (
        214 +                  <Badge variant="secondary">{result.node_types.join(" · ")}</Badge>
        215 +                )}
        216 +              </div>
        217 +              <pre className="bg-muted/40 overflow-x-auto rounded-md p-2 text-xs leading-relaxed">
        218 +                <code>{result.content}</code>
        219 +              </pre>
        220 +            </li>
        221 +          ))}
        222 +        </ul>
        223 +      </ScrollArea>
        224 +    </div>
        225 +  );
        226 +}
        227 +
   70   228  function SearchSkeleton() {
   71   229    return (
   72   230      <div className="space-y-2">

```
