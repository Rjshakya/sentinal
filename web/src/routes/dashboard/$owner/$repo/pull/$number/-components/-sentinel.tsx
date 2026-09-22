import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CommonCard } from "@/components/common-card";
import { CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/markdown";
import { usePullSentinel } from "@/lib/pulls";
import { formatRelative, shortSha, verdictStyle } from "@/lib/pull-utils";

import { DiffCommentCard } from "./-diff-comment-card";

type SentinelProps = {
  owner: string;
  repo: string;
  number: number;
};

export function SentinelTab({ owner, repo, number }: SentinelProps) {
  const { data, isLoading, isError, refetch } = usePullSentinel(owner, repo, number);

  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">Failed to load Sentinel review.</p>
        <Button variant="outline" className="mt-3" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (!data.review) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">
          No Sentinel review yet. Reviews run automatically when a pull request is
          opened or when Sentinel is mentioned.
        </p>
      </div>
    );
  }

  const review = data.review;
  const byFile = new Map<string, typeof data.comments>();
  for (const c of data.comments) {
    const list = byFile.get(c.fileName) ?? [];
    list.push(c);
    byFile.set(c.fileName, list);
  }

  return (
    <div className="flex flex-col gap-4">
      <CommonCard
        headerClassName="flex flex-row flex-wrap items-center gap-2 pb-2"
        header={
          <>
            <CardTitle className="text-base">Sentinel review</CardTitle>
            {data.summary && (
              <Badge className={verdictStyle(data.summary.verdict)}>
                {data.summary.verdict}
              </Badge>
            )}
            <Badge variant="outline">{review.state}</Badge>
            <span className="text-muted-foreground ml-auto font-mono text-xs">
              {shortSha(review.commitId)}
            </span>
          </>
        }
        body={
          <>
            <div className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {review.llmModel && <span>Model: {review.llmModel}</span>}
              {review.commentCount != null && <span>{review.commentCount} comments</span>}
              {review.createdAt && <span>{formatRelative(review.createdAt)}</span>}
            </div>
            {data.summary && (
              <>
                <Separator className="my-3" />
                <Markdown body={data.summary.summary} />
              </>
            )}
          </>
        }
      />

      {Array.from(byFile.entries()).map(([fileName, comments]) => (
        <CommonCard
          key={fileName}
          headerClassName="pb-2"
          header={<CardTitle className="font-mono text-sm font-medium">{fileName}</CardTitle>}
          bodyClassName="flex flex-col gap-3"
          body={
            <>
              {comments.map((c) => (
                <DiffCommentCard
                  key={c.id}
                  authorLogin="Sentinel"
                  createdAt={c.createdAt}
                  body={c.comment}
                  fromLine={c.fromLine}
                  toLine={c.toLine}
                  side={c.side === "LEFT" ? "LEFT" : "RIGHT"}
                  severity={c.severity}
                />
              ))}
            </>
          }
        />
      ))}

      {data.usage && (
        <p className="text-muted-foreground text-xs">
          Tokens: {data.usage.totalTokens.toLocaleString()} (in{" "}
          {data.usage.inputTokens.toLocaleString()} / out{" "}
          {data.usage.outputTokens.toLocaleString()}) · {data.usage.reviewStatus}
        </p>
      )}
    </div>
  );
}
