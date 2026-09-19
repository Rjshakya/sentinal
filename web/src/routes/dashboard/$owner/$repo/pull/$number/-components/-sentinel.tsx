import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Markdown } from "@/components/markdown";
import { usePullSentinel } from "@/lib/pulls";
import {
  SEVERITY_STYLES,
  formatDate,
  formatRelative,
  severityLabel,
  shortSha,
  verdictStyle,
} from "@/lib/pull-utils";

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
      <Card>
        <CardHeader className="flex flex-row flex-wrap items-center gap-2 pb-2">
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
        </CardHeader>
        <CardContent className="text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {review.llmModel && <span>Model: {review.llmModel}</span>}
          {review.commentCount != null && <span>{review.commentCount} comments</span>}
          {review.createdAt && <span>{formatRelative(review.createdAt)}</span>}
        </CardContent>
        {data.summary && (
          <CardContent>
            <Separator className="mb-3" />
            <Markdown body={data.summary.summary} />
          </CardContent>
        )}
      </Card>

      {Array.from(byFile.entries()).map(([fileName, comments]) => (
        <Card key={fileName}>
          <CardHeader className="pb-2">
            <CardTitle className="font-mono text-sm font-medium">{fileName}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {comments.map((c) => (
              <div key={c.id} className="rounded-md border p-3">
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <Badge className={SEVERITY_STYLES[c.severity] ?? ""}>
                    {severityLabel(c.severity)}
                  </Badge>
                  <span className="font-mono text-xs text-sky-600 dark:text-sky-400">
                    L{c.fromLine}
                    {c.toLine !== c.fromLine ? `–L${c.toLine}` : ""} · {c.side}
                  </span>
                  <span className="text-muted-foreground ml-auto text-xs">
                    {formatDate(c.createdAt)}
                  </span>
                </div>
                <Markdown body={c.comment} />
              </div>
            ))}
          </CardContent>
        </Card>
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
