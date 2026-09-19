import {
  prepareFileTreeInput,
  type FileTreePreparedInput,
  type GitStatusEntry,
} from "@pierre/trees";
import type { PRFileItem } from "./api";

export function toTreesStatus(status: string): GitStatusEntry["status"] {
  const s = status.toLowerCase();
  if (s === "removed" || s === "deleted") return "deleted";
  if (s === "added") return "added";
  if (s === "renamed") return "renamed";
  return "modified";
}

export type PullTreeInput = {
  preparedInput: FileTreePreparedInput;
  gitStatus: GitStatusEntry[];
  fileCount: number;
};

export function buildPullTreeInput(files: PRFileItem[]): PullTreeInput {
  const paths = files.map((f) => f.filename);
  return {
    preparedInput: prepareFileTreeInput(paths, {
      flattenEmptyDirectories: true,
    }),
    gitStatus: files.map((f) => ({
      path: f.filename,
      status: toTreesStatus(f.status),
    })),
    fileCount: files.length,
  };
}
