import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  apiClient,
  type ConfigureResponse,
  type Repo,
  type SetupRepo,
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

export function useSetup() {
  const qc = useQueryClient();
  return useMutation<ConfigureResponse, ApiError, SetupRepo[]>({
    mutationFn: (repos) => apiClient.setup(repos),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["github", "repos"] });
      qc.invalidateQueries({ queryKey: ["users", "repos"] });
    },
  });
}
