import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiClient, type Session } from "./api";
import { redirect, useRouter } from "@tanstack/react-router";

const SESSION_KEY = ["auth", "session"] as const;

export function useSession() {
  const data = useQuery<Session, ApiError>({
    queryKey: SESSION_KEY,
    queryFn: () => apiClient.session(),
    retry: false,
  });

  return data;
}

export const protectPage = async () => {
  try {
    const session = await apiClient.session();
    if (!session?.user_id) {
      throw redirect({ to: "/login" });
    }
  } catch (error) {
    throw redirect({ to: "/login" });
  }
};

export function useLogout() {
  const qc = useQueryClient();
  const router = useRouter();
  return useMutation({
    mutationFn: () => apiClient.logout(),
    onSuccess: () => {
      qc.setQueryData(SESSION_KEY, null);
      qc.invalidateQueries({ queryKey: SESSION_KEY });
      router.invalidate();
    },
  });
}
