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

export type Repo = {
  id: number;
  name: string;
  full_name: string;
  owner: string;
  private: boolean;
  description: string | null;
  default_branch: string;
  html_url: string;
  stargazers_count: number;
  language: string | null;
  updated_at: string;
};

export type IndexingRepo = {
  id: number;
  full_name: string;
  html_url: string;
};

export type IndexingResponse = {
  accepted: number;
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
  repos: () => request<Repo[]>("/github/repos"),
  startIndexing: (repos: IndexingRepo[]) =>
    request<IndexingResponse>("/ai/code/indexing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repos }),
    }),
};

export const apiBaseUrl = BASE;
