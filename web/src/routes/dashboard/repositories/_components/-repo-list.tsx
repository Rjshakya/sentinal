import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { Repo } from "@/lib/api";
import { IconGitPullRequest, IconLock } from "@tabler/icons-react";
import { Link } from "@tanstack/react-router";

type Props = {
  repos: Repo[];
  selected: Set<string>;
  onToggle: (fullName: string) => void;
};

export function RepoList({ repos, selected, onToggle }: Props) {
  return (
    <div className="divide-y rounded-lg ">
      {repos.map((repo) => {
        const isSelected = selected.has(repo.full_name);
        const isConfigured = repo.is_configured;
        const checkboxId = `repo-${repo.id}`;
        return (
          <Label
            key={repo.id}
            htmlFor={checkboxId}
            className={cn("flex items-start   gap-3 px-4 py-3 transition-colors")}
          >
            {isConfigured && <div className=" flex w-0.5 h-20  bg-green-500  " />}
            {isConfigured || (
              <Checkbox
                id={checkboxId}
                checked={isSelected}
                onCheckedChange={() => onToggle(repo.full_name)}
                className="mt-1"
              />
            )}
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate font-medium ">{repo.full_name}</span>
              </div>
              {repo.description && (
                <p className="text-muted-foreground line-clamp-1 text-xs  ">{repo.description}</p>
              )}

              <div className=" mt-4 flex items-center gap-1 ">
                {repo.language && (
                  <Badge className=" text-xs text-muted-foreground " variant={"secondary"}>
                    {" "}
                    {repo.language}{" "}
                  </Badge>
                )}
                {repo.private && (
                  <Badge variant="outline" className="gap-1  text-muted-foreground ">
                    <IconLock className="size-3" />
                    Private
                  </Badge>
                )}
              </div>
            </div>
            {isConfigured && (
              <Button
                size="sm"
                variant="outline"
                className="gap-1"
                render={
                  <Link
                    to="/dashboard/$owner/$repo/pulls"
                    params={{ owner: repo.owner, repo: repo.name }}
                    onClick={(e) => e.stopPropagation()}
                  />
                }
              >
                <IconGitPullRequest className="size-3.5" />
                {"Pulls"}
              </Button>
            )}
          </Label>
        );
      })}
    </div>
  );
}
