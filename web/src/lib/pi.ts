import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  apiClient,
  type PiConfig,
  type PiConfigPayload,
  type PiConfigUpsertResponse,
  type PiModelsResponse,
  type PiProvider,
} from "./api";

const PI_CONFIG_KEY = ["pi", "config"] as const;
const PI_PROVIDERS_KEY = ["pi", "providers"] as const;
const piModelsKey = (provider: string) => ["pi", "models", provider] as const;

export function usePiProviders() {
  return useQuery<PiProvider[], ApiError>({
    queryKey: PI_PROVIDERS_KEY,
    queryFn: () => apiClient.piProviders(),
  });
}

export function usePiModels(provider: string | null) {
  return useQuery<PiModelsResponse, ApiError>({
    queryKey: provider ? piModelsKey(provider) : ["pi", "models", "none"],
    // Never called while disabled (`enabled` below); the cast is safe.
    queryFn: () => apiClient.piModels(provider as string),
    enabled: provider !== null,
    staleTime: 1000 * 60 * 60,
  });
}

export function usePiConfig() {
  return useQuery<PiConfig | null, ApiError>({
    queryKey: PI_CONFIG_KEY,
    queryFn: () => apiClient.getPiConfig(),
  });
}

export function useSavePiConfig() {
  const queryClient = useQueryClient();
  return useMutation<PiConfigUpsertResponse, ApiError, PiConfigPayload>({
    mutationFn: (payload) => apiClient.savePiConfig(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PI_CONFIG_KEY });
    },
  });
}
