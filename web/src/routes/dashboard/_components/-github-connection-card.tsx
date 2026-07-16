import {
  IconBrandGithub,
  IconCircleCheck,
  IconCircleDashed,
  IconExternalLink,
  IconTrash,
} from "@tabler/icons-react";
import { useState } from "react";
import { toast } from "sonner";

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
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { githubAppManageUrl } from "@/lib/api";
import { useForgetInstallation, useInstallation, useInstallUrl } from "@/lib/installation";

export function GithubConnectionCard() {
  const { data: installation, isLoading } = useInstallation();

  const connected = !!installation?.connected;
  const installations = installation?.installations ?? [];

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
          ) : connected ? (
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
        ) : connected ? (
          <CardDescription>
            Sentinel will review pull requests on every repo you have granted it access to. Manage
            the access on GitHub.
          </CardDescription>
        ) : (
          <CardDescription>
            Install the Sentinel GitHub App on the accounts and organizations where you want
            AI-powered code reviews.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex-1" />
      <CardFooter>
        {isLoading ? (
          <Skeleton className="h-8 w-32" />
        ) : connected ? (
          <ConnectedControls installations={installations} />
        ) : (
          <InstallButton />
        )}
      </CardFooter>
    </Card>
  );
}

function InstallButton() {
  const { refetch, isFetching } = useInstallUrl();
  const [pending, setPending] = useState(false);

  async function handleClick() {
    setPending(true);
    try {
      const result = await refetch();
      if (result.data?.url) {
        window.open(result.data.url, "_blank", "noopener,noreferrer");
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to start install");
    } finally {
      setPending(false);
    }
  }

  return (
    <Button onClick={handleClick} disabled={pending || isFetching}>
      <IconBrandGithub />
      {pending || isFetching ? "Opening…" : "Install on GitHub"}
    </Button>
  );
}

type InstallationRow = {
  installation_id: string;
  github_installation_id: number;
  account_login: string;
  account_type: "User" | "Organization";
  repository_selection: "all" | "selected";
  suspended: boolean;
  repo_count: number;
};

function ConnectedControls({ installations }: { installations: InstallationRow[] }) {
  return (
    <div className="flex w-full flex-col gap-3">
      <Button
        variant="outline"
        render={<a href={githubAppManageUrl} target="_blank" rel="noreferrer" />}
      >
        <IconExternalLink />
        Manage on GitHub
      </Button>
      {installations.length > 0 && (
        <div className="space-y-2">
          {installations.map((inst) => (
            <ForgetInstallationRow key={inst.installation_id} installation={inst} />
          ))}
        </div>
      )}
    </div>
  );
}

function ForgetInstallationRow({ installation }: { installation: InstallationRow }) {
  const [open, setOpen] = useState(false);
  const forget = useForgetInstallation();
  const accountTypeLabel = installation.account_type === "Organization" ? "org" : "user";

  function handleConfirm() {
    forget.mutate(installation.installation_id, {
      onSuccess: () => {
        toast.success(`Forgot ${installation.account_login}`);
        setOpen(false);
      },
      onError: (err) => {
        toast.error(err.message);
      },
    });
  }

  return (
    <div className="bg-muted/40 flex items-center justify-between gap-2 rounded-md px-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{installation.account_login}</p>
        <p className="text-muted-foreground text-xs">
          {accountTypeLabel} · {installation.repo_count} indexed
          {installation.suspended ? " · suspended" : ""}
        </p>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogTrigger render={<Button size="sm" variant="ghost" />}>
          <IconTrash />
          Forget
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Forget this installation?</DialogTitle>
            <DialogDescription>
              Sentinel will stop tracking {installation.account_login} locally. The GitHub App
              itself stays installed — to fully revoke access, uninstall it on GitHub.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button variant="destructive" onClick={handleConfirm} disabled={forget.isPending}>
              <IconTrash />
              {forget.isPending ? "Forgetting…" : "Forget"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
