export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export function formatRelative(value: string | null): string {
  if (!value) return "—";
  const ms = Date.now() - new Date(value).getTime();
  if (Number.isNaN(ms)) return "—";
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.floor(months / 12)}y ago`;
}

export function shortSha(sha: string): string {
  return sha.length > 7 ? sha.slice(0, 7) : sha;
}

export const SEVERITY_STYLES: Record<string, string> = {
  P1_CRITICAL: "bg-destructive/10 text-destructive dark:bg-destructive/20",
  P2_WARNING: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  P3_NITPICK: "bg-secondary text-muted-foreground",
};

export function severityLabel(severity: string): string {
  if (severity === "P1_CRITICAL") return "P1";
  if (severity === "P2_WARNING") return "P2";
  if (severity === "P3_NITPICK") return "P3";
  return severity;
}

export function prStateLabel(item: {
  state: string;
  mergedAt: string | null;
  draft: boolean;
}): { label: string; className: string } {
  if (item.mergedAt) {
    return {
      label: "Merged",
      className: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
    };
  }
  if (item.state === "closed") {
    return {
      label: "Closed",
      className: "bg-destructive/10 text-destructive dark:bg-destructive/20",
    };
  }
  if (item.draft) {
    return {
      label: "Draft",
      className: "bg-secondary text-muted-foreground",
    };
  }
  return {
    label: "Open",
    className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  };
}

export function verdictStyle(verdict: string | null): string {
  if (verdict === "APPROVE")
    return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400";
  if (verdict === "REQUEST_CHANGES")
    return "bg-destructive/10 text-destructive dark:bg-destructive/20";
  return "bg-amber-500/10 text-amber-600 dark:text-amber-400";
}
