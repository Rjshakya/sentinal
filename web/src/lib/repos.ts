import { useMutation, useQuery } from "@tanstack/react-query";
import { ApiError, apiClient, type IndexingRepo, type IndexingResponse, type Repo } from "./api";

export function useRepos() {
  return useQuery<Repo[], ApiError>({
    queryKey: ["github", "repos"],
    queryFn: () => apiClient.repos(),
  });
}

export function useStartIndexing() {
  return useMutation<IndexingResponse, ApiError, IndexingRepo[]>({
    mutationFn: (repos) => apiClient.startIndexing(repos),
  });
}
