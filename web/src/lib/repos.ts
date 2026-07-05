import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  apiClient,
  type IndexingRepo,
  type IndexingResponse,
  type Repo,
  type UserRepo,
} from "./api";

export function useRepos() {
  return useQuery<Repo[], ApiError>({
    queryKey: ["github", "repos"],
    queryFn: () => apiClient.repos(),
  });
}

export function useUserRepos() {
  return useQuery<UserRepo[], ApiError>({
    queryKey: ["users", "repos"],
    queryFn: () => apiClient.userRepos(),
  });
}

export function useStartIndexing() {
  const qc = useQueryClient();
  return useMutation<IndexingResponse, ApiError, IndexingRepo[]>({
    mutationFn: (repos) => apiClient.startIndexing(repos),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users", "repos"] });
    },
  });
}
