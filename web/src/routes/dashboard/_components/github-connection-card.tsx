import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiBaseUrl } from "@/lib/api";
import { getGithubConnection, useConnections } from "@/lib/connections";
import {
  IconBrandGithub,
  IconCircleCheck,
  IconCircleDashed,
} from "@tabler/icons-react";

export function GithubConnectionCard() {
  const { data: connections, isLoading } = useConnections();
  const github = getGithubConnection(connections);

  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2">
            <IconBrandGithub className="size-5" />
            <CardTitle>GitHub</CardTitle>
          </div>
          {isLoading ? (
            <Skeleton className="h-5 w-24" />
          ) : github?.connected ? (
            <Badge>
              <IconCircleCheck />
              Connected
            </Badge>
          ) : (
            <Badge variant="secondary">
              <IconCircleDashed />
              Not connected
            </Badge>
          )}
        </div>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ) : github?.connected ? (
          <CardDescription>
            GitHub is connected. Reviews will run automatically on your PRs.
          </CardDescription>
        ) : (
          <CardDescription>
            Connect GitHub to enable AI-powered code reviews on your pull requests.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex-1" />
      <CardFooter>
        {isLoading ? (
          <Skeleton className="h-8 w-32" />
        ) : github?.connected ? (
          <Button variant="outline" disabled>
            <IconCircleCheck />
            Connected
          </Button>
        ) : (
          <Button render={<a href={`${apiBaseUrl}/pipes/connections/github/authorize`} />}>
            <IconBrandGithub />
            Connect GitHub
          </Button>
        )}
      </CardFooter>
    </Card>
  );
}
