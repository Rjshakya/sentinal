import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  apiClient,
  type IndexRepoTriggerIn,
  type IndexRepoTriggerOut,
} from "./api";

const REFETCH_AFTER_INDEX_MS = 5_000;

/**
 * Best-effort delay before re-fetching the GitHub repos list after
 * dispatching an index run. The DBOS workflow's first step
 * (``create_index_run_step``) inserts the ``STARTING`` row
 * synchronously, but the repo ``is_indexed`` mirror only flips to
 * ``true`` once the in-sandbox ingestion completes (~30s-2min for a
 * moderate repo). The delay lets the user see the in-flight state
 * without hammering the API; the eventual flip will surface on the
 * next refetch.
 */
export function useIndexRepo() {
  const qc = useQueryClient();
  return useMutation<IndexRepoTriggerOut, ApiError, IndexRepoTriggerIn>({
    mutationFn: (payload) => apiClient.indexRepo(payload),
    onSuccess: () => {
      window.setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["github", "repos"] });
      }, REFETCH_AFTER_INDEX_MS);
    },
  });
}
