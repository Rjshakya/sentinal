import { useQuery } from "@tanstack/react-query";

import { ApiError, apiClient, type Review } from "./api";

export function useReviews() {
  return useQuery<Review[], ApiError>({
    queryKey: ["review"],
    queryFn: () => apiClient.reviews(),
  });
}
