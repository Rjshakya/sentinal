import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import type { Review, ReviewState } from "@/lib/api";
import { useReviews } from "@/lib/reviews";
import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/dashboard/reviews")({
  component: ReviewsPage,
  beforeLoad: protectPage,
  ssr: false,
});

const STATE_STYLES: Record<ReviewState, { label: string; className: string }> = {
  SUCCESS: {
    label: "Success",
    className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  },
  FAILED: {
    label: "Failed",
    className: "bg-destructive/10 text-destructive dark:bg-destructive/20",
  },
  RUNNING: {
    label: "Running",
    className: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  },
  STARTING: {
    label: "Starting",
    className: "bg-secondary text-muted-foreground",
  },
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start || !end) return "—";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 0) return "—";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remSeconds}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function formatTokens(value: number): string {
  return value.toLocaleString();
}

function ReviewsPage() {
  const { data: reviews, isLoading, isError, refetch } = useReviews();

  if (isLoading) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="mx-auto flex w-full max-w-5xl p-6">
        <div className="w-full rounded-lg border p-6 text-center">
          <p className="text-muted-foreground text-sm">Failed to load reviews.</p>
          <Button variant="outline" className="mt-3" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-12 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reviews</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Review runs across your repositories.
        </p>
      </div>

      {!reviews || reviews.length === 0 ? (
        <div className="rounded-lg border p-6 text-center">
          <p className="text-muted-foreground text-sm">
            No reviews yet. Reviews run automatically when a pull request is
            opened or @<span className="font-mono">sentinel review</span> is
            mentioned.
          </p>
        </div>
      ) : (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Repository</TableHead>
                <TableHead>Pull Request</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>State</TableHead>
                <TableHead className="">Comments</TableHead>
                <TableHead>Model</TableHead>
                <TableHead className="">Tokens</TableHead>
                <TableHead>Started At</TableHead>
                <TableHead>Time Taken</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody className=" bg-accent dark:bg-card">
              {reviews.map((review) => (
                <ReviewRow key={review.id} review={review} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function ReviewRow({ review }: { review: Review }) {
  const state = STATE_STYLES[review.state];
  const repo =
    review.repo_owner && review.repo_name
      ? `${review.repo_owner}/${review.repo_name}`
      : "—";

  return (
    <TableRow className="">
      <TableCell className="border text-xs ">{repo}</TableCell>
      <TableCell className="border text-xs">
        <div className="flex items-center gap-2">
          <span className="text-muted-foreground text-xs">
            #{review.pr_number}
          </span>
          <span className="max-w-64 truncate">{review.pr_title ?? "—"}</span>

        </div>
      </TableCell>
      <TableCell className="border text-xs ">
        <span className="text-muted-foreground capitalize">
          {review.trigger ?? "—"}
        </span>
      </TableCell>
      <TableCell className="border text-xs">
        <Badge className={state.className}>{state.label}</Badge>
      </TableCell>
      <TableCell className="border text-xs">
        {review.comment_count ?? "—"}
      </TableCell>
      <TableCell className="border text-xs">
        <span className="text-muted-foreground">
          {review.llm_model ?? "—"}
        </span>
      </TableCell>
      <TableCell className="border text-xs">
        {review.usage
          ? formatTokens(review.usage.total_tokens)
          : "—"}
      </TableCell>
      <TableCell className=" border text-xs">
        <span className="text-muted-foreground">
          {formatDate(review.started_at)}
        </span>
      </TableCell>
      <TableCell className=" border text-xs">
        <span className="text-muted-foreground">
          {formatDuration(review.started_at, review.completed_at)}
        </span>
      </TableCell>
    </TableRow>
  );
}
