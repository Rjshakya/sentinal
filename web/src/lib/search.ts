import { useMutation } from "@tanstack/react-query";

import { ApiError, apiClient, type CodeSearchRequest, type CodeSearchResponse } from "./api";

export function useCodeSearch() {
  return useMutation<CodeSearchResponse, ApiError, CodeSearchRequest>({
    mutationFn: (payload) => apiClient.codeSearch(payload),
  });
}
