import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  apiClient,
  type LlmConfig,
  type LlmConfigPayload,
  type LlmConfigTestResponse,
  type LlmConfigUpsertResponse,
} from "./api";

const LLM_CONFIG_KEY = ["llm", "config"] as const;

export function useLlmConfig() {
  return useQuery<LlmConfig[], ApiError>({
    queryKey: LLM_CONFIG_KEY,
    queryFn: () => apiClient.getLlmConfig(),
  });
}

export function useUpdateLlmConfig() {
  const queryClient = useQueryClient();
  return useMutation<LlmConfigUpsertResponse, ApiError, LlmConfigPayload>({
    mutationFn: (payload) => apiClient.updateLlmConfig(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: LLM_CONFIG_KEY });
    },
  });
}

export function useTestLlmConfig() {
  return useMutation<LlmConfigTestResponse, ApiError, LlmConfigPayload>({
    mutationFn: (payload) => apiClient.testLlmConfig(payload),
  });
}
