import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
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
import { usePullCommits } from "@/lib/pulls";
import { formatRelative, shortSha } from "@/lib/pull-utils";

type CommitsProps = {
  owner: string;
  repo: string;
  number: number;
};

export function CommitsTab({ owner, repo, number }: CommitsProps) {
  const { data, isLoading, isError, refetch } = usePullCommits(owner, repo, number);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">Failed to load commits.</p>
        <Button variant="outline" className="mt-3" onClick={() => refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">No commits found.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Commit</TableHead>
            <TableHead>Author</TableHead>
            <TableHead>SHA</TableHead>
            <TableHead>Date</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((c) => {
            const headline = c.message.split("\n")[0] ?? c.message;
            return (
              <TableRow key={c.sha}>
                <TableCell className="max-w-96 truncate text-xs font-medium">
                  {headline}
                </TableCell>
                <TableCell>
                  <span className="flex items-center gap-2 text-xs">
                    <Avatar className="size-5">
                      {c.authorAvatar && (
                        <AvatarImage src={c.authorAvatar} alt={c.authorLogin} />
                      )}
                      <AvatarFallback>
                        {(c.authorLogin || c.authorName || "?").slice(0, 1).toUpperCase()}
                      </AvatarFallback>
                    </Avatar>
                    <span className="text-muted-foreground">
                      {c.authorLogin || c.authorName}
                    </span>
                  </span>
                </TableCell>
                <TableCell className="font-mono text-xs">{shortSha(c.sha)}</TableCell>
                <TableCell>
                  <span className="text-muted-foreground text-xs">
                    {formatRelative(c.date)}
                  </span>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
