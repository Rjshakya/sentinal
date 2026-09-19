import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/markdown";
import { usePullConversation, usePullDetail } from "@/lib/pulls";
import { formatRelative } from "@/lib/pull-utils";

type ConversationProps = {
  owner: string;
  repo: string;
  number: number;
};

type TimelineEntry = {
  key: string;
  at: string | null;
  node: React.ReactNode;
};

function reviewStateStyle(state: string): string {
  const s = state.toUpperCase();
  if (s === "APPROVED")
    return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (s === "CHANGES_REQUESTED")
    return "bg-destructive/10 text-destructive dark:bg-destructive/20";
  return "bg-secondary text-muted-foreground";
}

export function ConversationTab({ owner, repo, number }: ConversationProps) {
  const detail = usePullDetail(owner, repo, number);
  const { data, isLoading, isError, refetch } = usePullConversation(owner, repo, number);

  if (isLoading || detail.isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">Failed to load conversation.</p>
        <Button variant="outline" className="mt-3" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  const gh = detail.data?.github;

  const entries: TimelineEntry[] = [
    ...(gh
      ? [
          {
            key: "pr-body",
            at: null,
            node: (
              <Card>
                <CardHeader className="flex flex-row items-center gap-2 pb-2">
                  <Avatar className="size-6">
                    <AvatarFallback>{gh.author.slice(0, 1).toUpperCase()}</AvatarFallback>
                  </Avatar>
                  <span className="text-sm font-medium">{gh.author}</span>
                  <Badge variant="outline">Owner</Badge>
                </CardHeader>
                <CardContent>
                  <Markdown body={gh.body} />
                </CardContent>
              </Card>
            ),
          } satisfies TimelineEntry,
        ]
      : []),
    ...data.reviews.map(
      (r): TimelineEntry => ({
        key: `review-${r.id}`,
        at: r.submittedAt,
        node: (
          <Card>
            <CardContent className="flex items-center gap-2 pt-4 text-sm">
              <Avatar className="size-6">
                {r.authorAvatar && <AvatarImage src={r.authorAvatar} alt={r.authorLogin} />}
                <AvatarFallback>{r.authorLogin.slice(0, 1).toUpperCase()}</AvatarFallback>
              </Avatar>
              <span className="font-medium">{r.authorLogin}</span>
              <Badge className={reviewStateStyle(r.state)}>{r.state}</Badge>
              {r.submittedAt && (
                <span className="text-muted-foreground text-xs">
                  {formatRelative(r.submittedAt)}
                </span>
              )}
            </CardContent>
            {r.body.trim().length > 0 && (
              <CardContent>
                <Markdown body={r.body} />
              </CardContent>
            )}
          </Card>
        ),
      }),
    ),
    ...data.issueComments.map(
      (c): TimelineEntry => ({
        key: `issue-${c.id}`,
        at: c.createdAt,
        node: (
          <Card>
            <CardHeader className="flex flex-row items-center gap-2 pb-2">
              <Avatar className="size-6">
                {c.authorAvatar && <AvatarImage src={c.authorAvatar} alt={c.authorLogin} />}
                <AvatarFallback>{c.authorLogin.slice(0, 1).toUpperCase()}</AvatarFallback>
              </Avatar>
              <span className="text-sm font-medium">{c.authorLogin}</span>
              {c.createdAt && (
                <span className="text-muted-foreground text-xs">
                  commented {formatRelative(c.createdAt)}
                </span>
              )}
            </CardHeader>
            <CardContent>
              <Markdown body={c.body} />
            </CardContent>
          </Card>
        ),
      }),
    ),
    ...data.reviewComments.map(
      (c): TimelineEntry => ({
        key: `rc-${c.id}`,
        at: c.createdAt,
        node: (
          <Card>
            <CardHeader className="flex flex-row flex-wrap items-center gap-2 pb-2">
              <Avatar className="size-6">
                {c.authorAvatar && <AvatarImage src={c.authorAvatar} alt={c.authorLogin} />}
                <AvatarFallback>{c.authorLogin.slice(0, 1).toUpperCase()}</AvatarFallback>
              </Avatar>
              <span className="text-sm font-medium">{c.authorLogin}</span>
              <span className="font-mono text-xs text-sky-600 dark:text-sky-400">
                {c.path}
                {c.line != null ? `:L${c.line}` : ""}
              </span>
              {c.createdAt && (
                <span className="text-muted-foreground text-xs">
                  {formatRelative(c.createdAt)}
                </span>
              )}
            </CardHeader>
            <CardContent>
              <Markdown body={c.body} />
            </CardContent>
          </Card>
        ),
      }),
    ),
  ];

  if (entries.length === 0) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">No conversation yet.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {entries.map((e) => (
        <div key={e.key}>{e.node}</div>
      ))}
    </div>
  );
}
