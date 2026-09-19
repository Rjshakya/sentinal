import React from "react";
import { useQuery } from "@tanstack/react-query";
import { FileTree, useFileTree } from "@pierre/trees/react";

import { Skeleton } from "@/components/ui/skeleton";
import { pullFilesQueryOptions } from "@/lib/pulls";
import { buildPullTreeInput, type PullTreeInput } from "@/lib/pull-tree-input";
import { scrollToDiffFile } from "@/routes/dashboard/$owner/$repo/pull/$number/-components/-files-changed";

export function PullFilesTree({
  owner,
  repo,
  number,
}: {
  owner: string;
  repo: string;
  number: number;
}) {
  const { data: treeInput, isLoading, isError } = useQuery({
    ...pullFilesQueryOptions(owner, repo, number),
    select: buildPullTreeInput,
  });

  if (isLoading) {
    return (
      <div className="space-y-1 px-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-full" />
        ))}
      </div>
    );
  }

  if (isError || !treeInput || treeInput.fileCount === 0) {
    return (
      <p className="text-muted-foreground px-2 text-xs">
        {isError ? "Failed to load files." : "No changed files."}
      </p>
    );
  }

  return <TreeView treeInput={treeInput} />;
}

function TreeView({ treeInput }: { treeInput: PullTreeInput }) {
  const { model } = useFileTree({
    preparedInput: treeInput.preparedInput,
    gitStatus: treeInput.gitStatus,
    search: true,
    fileTreeSearchMode: "hide-non-matches",
    icons: "minimal",
    density: "compact",
    onSelectionChange: (selected) => {
      const first = selected[0];
      if (first) scrollToDiffFile(first);
    },
  });

  return (
    <FileTree
      model={model}
      className="h-100 bg-sidebar data-file-tree-search-container:padding-0 "
      style={
        {
          '--trees-theme-focus-ring': 'var(--ring)',
          '--trees-font-family': 'var(--default-mono-font-family)',
          '--trees-search-bg': 'var(--input)',
          '--trees-bg': 'var(--bg-sidebar)',
          '--trees-border-color': 'var(--border)',
          '--trees-padding-inline': "2px",
        } as React.CSSProperties
      }
    />
  );
}
