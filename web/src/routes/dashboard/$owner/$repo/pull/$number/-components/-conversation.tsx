import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { CommonCard } from "@/components/common-card";
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
        // {
        //   key: "pr-body",
        //   at: null,
        //   node: (
        //     <div className="p-1 ring-1 ring-foreground/10 grid gap-2">
        //       <CardHeader className="flex items-center gap-2 py-1 ">
        //         <Avatar className="size-6">
        //           <AvatarFallback>{gh.author.slice(0, 1).toUpperCase()}</AvatarFallback>
        //         </Avatar>
        //         <span className="text-sm font-medium">{gh.author}</span>
        //         <Badge variant="outline">Owner</Badge>
        //       </CardHeader>
        //
        //       <Card className="  bg-accent dark:bg-card ">
        //         <CardContent>
        //           <Markdown body={gh.body} />
        //         </CardContent>
        //       </Card>
        //     </div>
        //   ),
        // } satisfies TimelineEntry,
      ]
      : []),
    ...data.reviews.map(
      (r): TimelineEntry => ({
        key: `review-${r.id}`,
        at: r.submittedAt,
        node: (
          <CommonCard
            header={
              <div className="w-full flex items-center justify-between gap-2 ">
                <div className="flex items-center gap-2">
                  <Avatar className="size-6">
                    {r.authorAvatar && <AvatarImage src={r.authorAvatar} alt={r.authorLogin} />}
                    <AvatarFallback>{r.authorLogin.slice(0, 1).toUpperCase()}</AvatarFallback>
                  </Avatar>
                  <span className="font-medium">{r.authorLogin}</span>
                </div>
                {/* <Badge className={reviewStateStyle(r.state)}>{r.state}</Badge> */}
                {r.submittedAt && (
                  <span className="text-muted-foreground text-xs">
                    {formatRelative(r.submittedAt)}
                  </span>
                )}
              </div>
            }
            body={r.body.trim().length > 0 ? <Markdown body={r.body} /> : undefined}
          />
        ),
      }),
    ),
    ...data.issueComments.map(
      (c): TimelineEntry => ({
        key: `issue-${c.id}`,
        at: c.createdAt,
        node: (
          <CommonCard
            header={
              <>
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
              </>
            }
            body={<Markdown body={c.body} />}
          />
        ),
      }),
    ),
    ...data.reviewComments.map(
      (c): TimelineEntry => ({
        key: `rc-${c.id}`,
        at: c.createdAt,
        node: (
          <CommonCard
            headerClassName="flex flex-wrap items-center gap-2 py-1"
            header={
              <div className=" w-full grid gap-2 ">
                <div className="flex items-center justify-between gap-2">
                  <div className=" flex items-center gap-2">
                    <Avatar className="size-6">
                      {c.authorAvatar && <AvatarImage src={c.authorAvatar} alt={c.authorLogin} />}
                      <AvatarFallback>{c.authorLogin.slice(0, 1).toUpperCase()}</AvatarFallback>
                    </Avatar>
                    <span className="text-sm font-medium">{c.authorLogin}</span>
                  </div>

                  {c.createdAt && (
                    <span className="text-muted-foreground text-xs">
                      {formatRelative(c.createdAt)}
                    </span>
                  )}

                </div>

              </div>
            }
            body={<Markdown body={c.body} />}
            footer={<div className="truncate font-mono text-xs text-sky-600 dark:text-sky-400">
              {c.path}
              {c.line != null ? `:L${c.line}` : ""}
            </div>
            }
          />
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
