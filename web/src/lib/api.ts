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
  github_login: string | null;
};

export type InstallationSummary = {
  installation_id: string;
  github_installation_id: number;
  account_login: string;
  account_type: "User" | "Organization";
  repository_selection: "all" | "selected";
  suspended: boolean;
  repo_count: number;
};

export type InstallationState = {
  connected: boolean;
  installation_count: number;
  installations: InstallationSummary[];
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
  clone_url: string;
  installation_id: string;
  github_installation_id: number;
  is_configured: boolean;
};

export type SetupRepo = {
  id: number;
  owner: string;
  name: string;
  installation_id: string;
};

export type SetupEcosystem = "node" | "python" | "rust" | "go" | "ruby" | "mixed" | "none";

export type SetupResult = {
  ok: boolean;
  ecosystem: SetupEcosystem;
  manager: string | null;
  install_cmd: string | null;
  duration_s: number;
  notes: string;
  bootstrapped_tools: string[];
};

export type RepoSetupResult = {
  repo_id: string | null;
  github_repo_id: number;
  setup: SetupResult;
};

export type SetupAck = {
  results: RepoSetupResult[];
};

export type CodeSearchRequest = {
  repo_id: string;
  repo_name: string;
  query: string;
  limit?: number;
};

export type CodeSearchResult = {
  id?: string | number;
  file_name?: string;
  start_line?: number;
  end_line?: number;
  content?: string;
  node_types?: string | string[] | null;
  language?: string | null;
  _relevance_score?: number;
};

export type CodeSearchResponse = {
  repo_name?: string;
  query?: string;
  results?: CodeSearchResult[];
};

export type UserRepo = {
  id: string;
  user_id: string;
  org_id: string | null;
  repo_name: string;
  repo_owner: string;
  url: string | null;
  private: boolean;
  default_branch: string | null;
  created_at: string;
  updated_at: string;
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
  installation: () => request<InstallationState>("/github/installation"),
  forgetInstallation: (installationId: string) =>
    request<void>(`/github/installation/${installationId}`, { method: "DELETE" }),
  repos: () => request<Repo[]>("/github/repos"),
  userRepos: () => request<UserRepo[]>("/users/repos"),
  setup: (repos: SetupRepo[]) =>
    request<SetupAck>("/ai/repo/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repos }),
    }),
  codeSearch: (payload: CodeSearchRequest) =>
    request<CodeSearchResponse>("/ai/code/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  installUrl: () => request<{ url: string }>("/github/install-url"),
};

export const apiBaseUrl = BASE;
export const githubAppManageUrl = "https://github.com/settings/installations";
