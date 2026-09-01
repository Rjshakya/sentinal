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
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
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
                <TableHead className="text-right">Comments</TableHead>
                <TableHead>Model</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead>Completed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
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
    <TableRow>
      <TableCell className="font-medium">{repo}</TableCell>
      <TableCell>
        <div className="flex flex-col">
          <span className="max-w-64 truncate">{review.pr_title ?? "—"}</span>
          <span className="text-muted-foreground text-xs">
            #{review.pr_number}
          </span>
        </div>
      </TableCell>
      <TableCell>
        <span className="text-muted-foreground capitalize">
          {review.trigger ?? "—"}
        </span>
      </TableCell>
      <TableCell>
        <Badge className={state.className}>{state.label}</Badge>
      </TableCell>
      <TableCell className="text-right">
        {review.comment_count ?? "—"}
      </TableCell>
      <TableCell>
        <span className="text-muted-foreground">
          {review.llm_model ?? "—"}
        </span>
      </TableCell>
      <TableCell className="text-right">
        {review.usage
          ? formatTokens(review.usage.total_tokens)
          : "—"}
      </TableCell>
      <TableCell>
        <span className="text-muted-foreground">
          {formatDate(review.completed_at ?? review.created_at)}
        </span>
      </TableCell>
    </TableRow>
  );
}
