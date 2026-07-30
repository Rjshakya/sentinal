import { useQuery } from "@tanstack/react-query";

import { ApiError, apiClient, type UserStats } from "./api";

export function useUserStats() {
  return useQuery<UserStats, ApiError>({
    queryKey: ["users", "stats"],
    queryFn: () => apiClient.userStats(),
  });
}
