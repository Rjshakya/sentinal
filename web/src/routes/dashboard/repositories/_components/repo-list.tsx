import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { Repo } from "@/lib/api";
import { IconCircleCheck, IconLock, IconStar, IconStarFilled } from "@tabler/icons-react";

type Props = {
  repos: Repo[];
  selected: Set<string>;
  onToggle: (fullName: string) => void;
  indexed: Set<string>;
};

export function RepoList({ repos, selected, onToggle, indexed }: Props) {
  return (
    <div className="divide-y rounded-lg border">
      {repos.map((repo) => {
        const isIndexed = indexed.has(String(repo.id));
        const isSelected = isIndexed || selected.has(repo.full_name);
        const checkboxId = `repo-${repo.id}`;
        return (
          <Label
            key={repo.id}
            htmlFor={checkboxId}
            className="hover:bg-muted/50 flex cursor-pointer items-start gap-3 px-4 py-3 transition-colors"
          >
            <Checkbox
              id={checkboxId}
              checked={isSelected}
              disabled={isIndexed}
              onCheckedChange={() => onToggle(repo.full_name)}
              className="mt-1"
            />
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="truncate font-medium">{repo.full_name}</span>
                {isIndexed && (
                  <Badge variant="secondary" className="gap-1">
                    <IconCircleCheck className="size-3" />
                    Indexed
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
