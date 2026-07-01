const BASE = import.meta.env.VITE_API_URL as string;

export type Session = {
  user_id: string;
  user_name: string | null;
  email: string;
  profile_picture: string | null;
  session_id: string;
  external_id: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type Connection = {
  slug: string;
  name: string;
  connected: boolean;
  connected_at: string | null;
};

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`API ${status}: ${body || "(no body)"}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, body);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const apiClient = {
  session: () => request<Session>("/auth/session"),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  connections: () => request<Connection[]>("/pipes/connections"),
  connectGitHub: () => request<void>("/pipes/connections/github/authorize"),
};

export const apiBaseUrl = BASE;
