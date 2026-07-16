import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiClient, type InstallationState } from "./api";

const INSTALLATION_KEY = ["github", "installation"] as const;
const INSTALL_URL_KEY = ["github", "install-url"] as const;

export function useInstallation() {
  return useQuery<InstallationState, ApiError>({
    queryKey: INSTALLATION_KEY,
    queryFn: () => apiClient.installation(),
  });
}

export function useInstallUrl() {
  return useQuery<{ url: string }, ApiError>({
    queryKey: INSTALL_URL_KEY,
    queryFn: () => apiClient.installUrl(),
    enabled: false,
    staleTime: 0,
  });
}

export function useForgetInstallation() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (installationId) => apiClient.forgetInstallation(installationId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: INSTALLATION_KEY });
      qc.invalidateQueries({ queryKey: ["github", "repos"] });
      qc.invalidateQueries({ queryKey: ["users", "repos"] });
    },
  });
}
