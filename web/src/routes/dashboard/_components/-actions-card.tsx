import { Link } from "@tanstack/react-router";
import { IconCircleCheck } from "@tabler/icons-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CommonCard } from "@/components/common-card";
import { CardDescription, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useInstallation } from "@/lib/installation";

import { GithubConnectionCard } from "./-github-connection-card";
import { NavIcons } from "@/lib/nav";

export function ActionsCard() {
  const { data: installation, isLoading } = useInstallation();
  const connected = !!installation?.connected;

  if (isLoading) {
    return (
      <CommonCard
        header={
          <>
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-4 w-full" />
          </>
        }
        body={<Skeleton className="h-9 w-48" />}
      />
    );
  }

  if (!connected) {
    return <GithubConnectionCard />;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <CardTitle className="text-lg">Actions</CardTitle>
      </div>

      <CommonCard
        header={
          <div className=" w-full flex items-center justify-between gap-2">
            <CardTitle>Github</CardTitle>
            <Badge className="text-green-600" variant="ghost">
              <IconCircleCheck />
              connected
            </Badge>
          </div>
        }
        body={
          <CardDescription>
            You&apos;re connected. Pick the repositories Sentinel should review.
          </CardDescription>
        }
        bodyClassName="grid gap-4"
        footer={
          <Button variant="outline" render={<Link to="/dashboard/repositories" />}>
            {NavIcons.folder}
            Configure repositories
          </Button>
        }
      />
    </div>
  );
}
