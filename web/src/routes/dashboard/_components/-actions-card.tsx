import { Link } from "@tanstack/react-router";
import { IconCircleCheck, IconFolders } from "@tabler/icons-react";

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
import { useInstallation } from "@/lib/installation";

import { GithubConnectionCard } from "./-github-connection-card";
import { NavIcons } from "@/lib/nav";

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
    <div className="flex flex-col gap-4 ">
      <div className="flex items-center gap-2">
        <CardTitle className="text-lg">Actions</CardTitle>
      </div>

      <div className="grid gap-2 p-1.5 ring-1 ring-foreground/10">
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle>Github</CardTitle>

            <Badge className="text-green-600 " variant={"ghost"}>
              <IconCircleCheck />
              connected
            </Badge>
          </div>
        </CardHeader>

        <Card className="bg-accent dark:bg-card ">
          <CardContent className="grid gap-4">
            <CardDescription>
              You&apos;re connected. Pick the repositories Sentinel should review.
            </CardDescription>
          </CardContent>
          <CardFooter>
            <Button variant={"outline"} render={<Link to="/dashboard/repositories" />}>
              {NavIcons.folder}
              Configure repositories
            </Button>
          </CardFooter>
        </Card>
      </div>
    </div>
  );
}
