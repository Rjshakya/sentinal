import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { Repo } from "@/lib/api";
import { IconCircleCheck, IconLock, IconStar, IconStarFilled } from "@tabler/icons-react";

type Props = {
  repos: Repo[];
  selected: Set<string>;
  onToggle: (fullName: string) => void;
};

export function RepoList({ repos, selected, onToggle }: Props) {
  return (
    <div className="divide-y rounded-lg border">
      {repos.map((repo) => {
        const isSelected = selected.has(repo.full_name);
        const isConfigured = repo.is_configured;
        const checkboxId = `repo-${repo.id}`;
        return (
          <Label
            key={repo.id}
            htmlFor={checkboxId}
            className={cn(
              "flex items-start gap-3 px-4 py-3 transition-colors",
              isConfigured
                ? "border-l-2 border-l-emerald-500/70 bg-emerald-50/30 dark:bg-emerald-950/20 cursor-default"
                : "hover:bg-muted/50 cursor-pointer",
            )}
          >
            <Checkbox
              id={checkboxId}
              checked={isSelected}
              disabled={isConfigured}
              onCheckedChange={() => {
                if (!isConfigured) onToggle(repo.full_name);
              }}
              className="mt-1"
            />
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate font-medium">{repo.full_name}</span>
                {isConfigured && (
                  <Badge
                    variant="default"
                    className="gap-1 border-emerald-600/40 bg-emerald-600/15 text-emerald-700 dark:text-emerald-300"
                  >
                    <IconCircleCheck className="size-3" />
                    Configured
                  </Badge>
                )}
                {repo.private && (
                  <Badge variant="outline" className="gap-1">
                    <IconLock className="size-3" />
                    Private
                  </Badge>
                )}
                {repo.language && <Badge variant="secondary">{repo.language}</Badge>}
                <span className="text-muted-foreground flex items-center gap-1 text-xs">
                  {repo.stargazers_count > 0 ? (
                    <IconStarFilled className="size-3" />
                  ) : (
                    <IconStar className="size-3" />
                  )}
                  {repo.stargazers_count.toLocaleString()}
                </span>
              </div>
              {repo.description && (
                <p className="text-muted-foreground line-clamp-2 text-sm">{repo.description}</p>
              )}
            </div>
          </Label>
        );
      })}
    </div>
  );
}
