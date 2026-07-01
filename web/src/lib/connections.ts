import { useQuery } from "@tanstack/react-query";
import { ApiError, apiClient, type Connection } from "./api";

const CONNECTIONS_KEY = ["pipes", "connections"] as const;

export function useConnections() {
  return useQuery<Connection[], ApiError>({
    queryKey: CONNECTIONS_KEY,
    queryFn: () => apiClient.connections(),
    staleTime: 30_000,
  });
}

export function getGithubConnection(
  connections: Connection[] | undefined,
): Connection | undefined {
  return connections?.find((c) => c.slug === "github");
}
