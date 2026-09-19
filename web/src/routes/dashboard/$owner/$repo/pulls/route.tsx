import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { protectPage } from "@/lib/auth";
import type { PRListItem, PullsState } from "@/lib/api";
import { usePulls } from "@/lib/pulls";
import { formatRelative, prStateLabel } from "@/lib/pull-utils";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/dashboard/$owner/$repo/pulls")({
  component: PullsPage,
  beforeLoad: protectPage,
  ssr: false,
});

function PullsPage() {
  const { owner, repo } = Route.useParams();
  const [state, setState] = useState<PullsState>("open");
  const { data: pulls, isLoading, isError, refetch } = usePulls(owner, repo, state);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-12 p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {owner}/{repo}
          </h1>
          <p className="text-muted-foreground mt-1 text-sm">Pull requests.</p>
        </div>
        <Select
          value={state}
          onValueChange={(v) => setState(v as PullsState)}
        >
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="open">Open</SelectItem>
            <SelectItem value="closed">Closed</SelectItem>
            <SelectItem value="all">All</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <div className="rounded-lg border p-6 text-center">
          <p className="text-muted-foreground text-sm">Failed to load pull requests.</p>
          <Button variant="outline" className="mt-3" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      )}

      {!isLoading && !isError && (!pulls || pulls.length === 0) && (
        <div className="rounded-lg border p-6 text-center">
          <p className="text-muted-foreground text-sm">
            No {state === "all" ? "" : `${state} `}pull requests found.
          </p>
        </div>
      )}

      {!isLoading && !isError && pulls && pulls.length > 0 && (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Pull Request</TableHead>
                <TableHead>Author</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Branch</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pulls.map((pr) => (
                <PullRow key={pr.number} pr={pr} owner={owner} repo={repo} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function PullRow({
  pr,
  owner,
  repo,
}: {
  pr: PRListItem;
  owner: string;
  repo: string;
}) {
  const state = prStateLabel(pr);
  return (
    <TableRow>
      <TableCell className="">
        <Link
          to="/dashboard/$owner/$repo/pull/$number"
          params={{ owner, repo, number: String(pr.number) }}
          search={{ tab: "conversation" }}
          className="flex items-center gap-2 hover:underline"
        >
          <span className="text-muted-foreground text-xs">#{pr.number}</span>
          <span className="max-w-80 truncate font-medium">{pr.title}</span>
        </Link>
      </TableCell>
      <TableCell>
        <span className="flex items-center gap-2 text-xs">
          <Avatar className="size-5">
            {pr.authorAvatar && <AvatarImage src={pr.authorAvatar} alt={pr.author} />}
            <AvatarFallback>{pr.author.slice(0, 1).toUpperCase()}</AvatarFallback>
          </Avatar>
          <span className="text-muted-foreground">{pr.author}</span>
        </span>
      </TableCell>
      <TableCell>
        <Badge className={cn(state.className, "w-full")}>{state.label}</Badge>
      </TableCell>
      <TableCell className="text-xs">
        <span className="font-mono">{pr.headBranch}</span>
        <span className="text-muted-foreground"> → </span>
        <span className="font-mono">{pr.baseBranch}</span>
      </TableCell>
      <TableCell>
        <span className="text-muted-foreground text-xs">
          {formatRelative(pr.updatedAt)}
        </span>
      </TableCell>
    </TableRow>
  );
}
