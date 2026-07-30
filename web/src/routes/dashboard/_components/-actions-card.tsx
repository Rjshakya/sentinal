import { Link } from "@tanstack/react-router";
import { IconBrandGithub, IconCircleCheck, IconFolders } from "@tabler/icons-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useInstallation } from "@/lib/installation";

import { GithubConnectionCard } from "./-github-connection-card";

export function ActionsCard() {
  const { data: installation, isLoading } = useInstallation();
  const connected = !!installation?.connected;

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-4 w-full" />
        </CardHeader>
        <CardContent>
          <Skeleton className="h-9 w-48" />
        </CardContent>
      </Card>
    );
  }

  if (!connected) {
    return <GithubConnectionCard />;
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <IconBrandGithub className="size-5" />
            <CardTitle>Actions</CardTitle>
          </div>
          <Badge>
            <IconCircleCheck />
            GitHub connected
          </Badge>
        </div>
        <CardDescription>
          You&apos;re connected. Pick the repositories Sentinel should review.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button render={<Link to="/dashboard/repositories" />}>
          <IconFolders />
          Configure repositories
        </Button>
      </CardContent>
    </Card>
  );
}
