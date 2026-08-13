import { createFileRoute, Link } from "@tanstack/react-router";
import { IconArrowLeft } from "@tabler/icons-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { protectPage } from "@/lib/auth";
import { useCodeSearch } from "@/lib/search";
import { SearchResults } from "./-components/search-results";

export const Route = createFileRoute("/dashboard/search/$owner/$name")({
  component: SearchPage,
  beforeLoad: protectPage,
  ssr: false,
});

function SearchPage() {
  const { owner, name } = Route.useParams();
  const [query, setQuery] = useState("");
  const search = useCodeSearch();

  function handleSearch() {
    if (query.trim().length <= 0 && !search.isPending) return;
    search.mutate({ owner, repo: name, query: query.trim(), limit: 20 });
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
          <h1 className="mt-8 text-2xl font-semibold tracking-tight">
            {owner}/{name}
          </h1>
        </div>
      </div>

      <Card className="py-0 pt-1 pb-1 px-1  ">
        <CardHeader className="p-0  ">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <Input
              className=" bg-card dark:bg-card h-10  border-0 border-b  focus-visible:ring-0 focus-visible:border-b   px-1  "
              value={query}
              onChange={(e) => setQuery(e.currentTarget.value)}
              placeholder="e.g. how does auth middleware attach the session?"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch();
              }}
            />
          </div>
        </CardHeader>
        <CardContent className="space-y-3  bg-background  py-5">
          {search.isPending && <SearchSkeleton />}
          {search.data && !search.isPending && (
            <SearchResults results={search.data?.results || []} owner={owner} repo={name} />
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
