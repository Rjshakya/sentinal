import { createFileRoute, Link } from "@tanstack/react-router";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { protectPage } from "@/lib/auth";
import { pullFilesQueryOptions, usePullDetail } from "@/lib/pulls";
import { queryClient } from "@/lib/query-client";
import { CommitsTab } from "./-components/-commits";
import { ConversationTab } from "./-components/-conversation";
import { FilesChangedTab } from "./-components/-files-changed";
import { SentinelTab } from "./-components/-sentinel";

const TABS = ["conversation", "commits", "files", "sentinel"] as const;
export type PullTab = (typeof TABS)[number];

function isPullTab(value: unknown): value is PullTab {
  return typeof value === "string" && (TABS as readonly string[]).includes(value);
}

export const Route = createFileRoute("/dashboard/$owner/$repo/pull/$number")({
  component: PullDetailPage,
  beforeLoad: protectPage,
  ssr: false,
  loader: ({ params }) =>
    queryClient.ensureQueryData(
      pullFilesQueryOptions(params.owner, params.repo, Number(params.number)),
    ),
  validateSearch: (search: Record<string, unknown>): { tab: PullTab } => ({
    tab: isPullTab(search.tab) ? search.tab : "conversation",
  }),
});

function PullDetailPage() {
  const { owner, repo, number } = Route.useParams();
  const { tab } = Route.useSearch();
  const navigate = Route.useNavigate();
  const prNumber = Number(number);
  const { data: detail, isLoading, isError, refetch } = usePullDetail(owner, repo, prNumber);

  if (isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="h-5 w-1/2" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (isError || !detail) {
    return (
      <div className="mx-auto flex w-full max-w-5xl p-6">
        <div className="w-full rounded-lg border p-6 text-center">
          <p className="text-muted-foreground text-sm">Failed to load pull request.</p>
          <Button variant="outline" className="mt-3" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const gh = detail.github;
  const stateBadge = gh.merged ? (
    <Badge className="bg-violet-500/10 text-violet-600 dark:text-violet-400">Merged</Badge>
  ) : gh.state === "closed" ? (
    <Badge className="bg-destructive/10 text-destructive dark:bg-destructive/20">Closed</Badge>
  ) : (
    <Badge className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400">Open</Badge>
  );

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
      <Breadcrumb>
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink
              render={
                <Link to="/dashboard/$owner/$repo/pulls" params={{ owner, repo }} />
              }
            >
              {owner}/{repo}
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbLink
              render={
                <Link to="/dashboard/$owner/$repo/pulls" params={{ owner, repo }} />
              }
            >
              pulls
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>#{detail.number}</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">{gh.title}</h1>
          <span className="text-muted-foreground text-xl font-normal">#{detail.number}</span>
          {stateBadge}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
          <span className="flex items-center gap-1.5">
            <Avatar className="size-5">
              <AvatarFallback>{gh.author.slice(0, 1).toUpperCase()}</AvatarFallback>
            </Avatar>
            <span className="font-medium">{gh.author || "—"}</span>
          </span>
          <span className="text-muted-foreground">
            wants to merge into{" "}
            <span className="font-mono text-xs">{gh.baseBranch}</span> from{" "}
            <span className="font-mono text-xs">{gh.headBranch}</span>
          </span>
          <span className="text-xs">
            <span className="text-emerald-600 dark:text-emerald-400">+{gh.additions}</span>{" "}
            <span className="text-destructive">−{gh.deletions}</span>
            <span className="text-muted-foreground"> · {gh.changedFiles} files</span>
          </span>
        </div>
      </div>

      <Tabs
        value={tab}
        onValueChange={(v) => {
          if (isPullTab(v)) navigate({ search: { tab: v } });
        }}
      >
        <TabsList>
          <TabsTrigger value="conversation">Conversation</TabsTrigger>
          <TabsTrigger value="commits">Commits</TabsTrigger>
          <TabsTrigger value="files">Files changed</TabsTrigger>
          <TabsTrigger value="sentinel">Sentinel</TabsTrigger>
        </TabsList>
        <TabsContent value="conversation">
          <ConversationTab owner={owner} repo={repo} number={prNumber} />
        </TabsContent>
        <TabsContent value="commits">
          <CommitsTab owner={owner} repo={repo} number={prNumber} />
        </TabsContent>
        <TabsContent value="files">
          <FilesChangedTab owner={owner} repo={repo} number={prNumber} />
        </TabsContent>
        <TabsContent value="sentinel">
          <SentinelTab owner={owner} repo={repo} number={prNumber} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
