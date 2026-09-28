import { queryOptions, useQuery } from "@tanstack/react-query";
import {
  ApiError,
  apiClient,
  type Conversation,
  type PRCommitItem,
  type PRFileItem,
  type PRListItem,
  type PullDetail,
  type PullsState,
  type SentinelDetail,
} from "./api";

export function usePulls(owner: string, repo: string, state: PullsState) {
  return useQuery<PRListItem[], ApiError>({
    queryKey: ["pulls", owner, repo, state],
    queryFn: () => apiClient.pulls(owner, repo, state),
  });
}

export function usePullDetail(owner: string, repo: string, number: number) {
  return useQuery<PullDetail, ApiError>({
    queryKey: ["pulls", owner, repo, number, "detail"],
    queryFn: () => apiClient.pullDetail(owner, repo, number),
  });
}

export function usePullCommits(owner: string, repo: string, number: number) {
  return useQuery<PRCommitItem[], ApiError>({
    queryKey: ["pulls", owner, repo, number, "commits"],
    queryFn: () => apiClient.pullCommits(owner, repo, number),
  });
}

async function fetchAllPullFiles(
  owner: string,
  repo: string,
  number: number,
): Promise<PRFileItem[]> {
  const all: PRFileItem[] = [];
  let page = 1;
  for (; ;) {
    const res = await apiClient.pullFilesPage(owner, repo, number, page);
    all.push(...res.files);
    if (res.files.length < 100 || all.length >= res.total) break;
    page += 1;
    if (page > 10) break;
  }
  return all;
}

export function pullFilesQueryOptions(owner: string, repo: string, number: number) {
  return queryOptions<PRFileItem[], ApiError>({
    queryKey: ["pulls", owner, repo, number, "files"],
    queryFn: () => fetchAllPullFiles(owner, repo, number),
  });
}

export function usePullFilesAll(owner: string, repo: string, number: number) {
  return useQuery<PRFileItem[], ApiError>(pullFilesQueryOptions(owner, repo, number));
}

export function usePullConversation(
  owner: string,
  repo: string,
  number: number,
) {
  return useQuery<Conversation, ApiError>({
    queryKey: ["pulls", owner, repo, number, "conversation"],
    queryFn: () => apiClient.pullConversation(owner, repo, number),
  });
}

export function usePullSentinel(
  owner: string,
  repo: string,
  number: number,
  reviewId?: string,
) {
  return useQuery<SentinelDetail, ApiError>({
    queryKey: ["pulls", owner, repo, number, "sentinel", reviewId ?? "latest"],
    queryFn: () => apiClient.pullSentinel(owner, repo, number, reviewId),
  });
}
