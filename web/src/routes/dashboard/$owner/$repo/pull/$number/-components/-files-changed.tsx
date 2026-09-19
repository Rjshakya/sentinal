import { Component, useMemo, useState, type ReactNode } from "react";
import {
  PatchDiff,
  type DiffLineAnnotation,
  type FileDiffOptions,
} from "@pierre/diffs/react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { Card, CardContent } from "@/components/ui/card";
import { Markdown } from "@/components/markdown";
import { useTheme } from "@/components/theme-provider";
import type { PRFileItem, SentinelComment } from "@/lib/api";
import { usePullFilesAll, usePullSentinel } from "@/lib/pulls";
import { SEVERITY_STYLES, severityLabel } from "@/lib/pull-utils";
import { Skeleton } from "@/components/ui/skeleton";

type FilesProps = {
  owner: string;
  repo: string;
  number: number;
};

type SentinelAnnotationMeta = {
  commentId: string;
  severity: string;
  comment: string;
  fromLine: number;
  toLine: number;
};

type DiffView = "unified" | "split";

function diffAnchor(filename: string): string {
  return `diff-${filename}`;
}

export function scrollToDiffFile(filename: string): void {
  document
    .getElementById(diffAnchor(filename))
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Rebuild a complete unified-diff document around GitHub's hunk-only
 * `patch` block.
 *
 * `GET /pulls/{n}/files` returns `patch` starting directly at the first
 * `@@` hunk, with no `---`/`+++` file headers — but `PatchDiff` parses
 * via `parsePatchFiles`, which splits input into per-file blobs on file
 * boundaries and throws ("must contain exactly 1 file diff") when the
 * input yields zero files. The backend passes GitHub's payload through
 * verbatim, so the envelope is reconstructed here from the file's
 * `status` (+ `previousFilename` for renames).
 */
export function toFullPatch(file: PRFileItem): string | null {
  if (!file.patch) return null;
  const body = file.patch;
  if (
    body.startsWith("diff --git") ||
    body.startsWith("--- ") ||
    body.startsWith("*** ")
  ) {
    return body;
  }
  const status = file.status.toLowerCase();
  const prev = file.previousFilename;
  const renamed = prev != null && prev !== "" && prev !== file.filename;
  // Git-style envelopes: the `diff --git` line routes the parser down its
  // git path (strips `a/`/`b/` prefixes, detects `new`/`deleted` types from
  // the mode lines). Verified against the installed `parsePatchFiles`.
  let header: string;
  if (status === "added") {
    header =
      `diff --git a/${file.filename} b/${file.filename}\n` +
      `new file mode 100644\n` +
      `--- /dev/null\n` +
      `+++ b/${file.filename}\n`;
  } else if (status === "removed" || status === "deleted") {
    header =
      `diff --git a/${file.filename} b/${file.filename}\n` +
      `deleted file mode 100644\n` +
      `--- a/${file.filename}\n` +
      `+++ /dev/null\n`;
  } else if (status === "renamed" || status === "copied" || renamed) {
    const from = renamed && prev ? prev : file.filename;
    header =
      `diff --git a/${from} b/${file.filename}\n` +
      `rename from ${from}\n` +
      `rename to ${file.filename}\n` +
      `--- a/${from}\n` +
      `+++ b/${file.filename}\n`;
  } else {
    header =
      `diff --git a/${file.filename} b/${file.filename}\n` +
      `--- a/${file.filename}\n` +
      `+++ b/${file.filename}\n`;
  }
  const normalized = body.endsWith("\n") ? body : `${body}\n`;
  return `${header}${normalized}`;
}

function UnparsableDiffFallback({ file }: { file: PRFileItem }) {
  return (
    <Card id={diffAnchor(file.filename)} className="scroll-mt-20">
      <CardContent className="flex flex-wrap items-center gap-2 pt-4 text-sm">
        <span className="font-mono text-xs font-medium">{file.filename}</span>
        <Badge variant="outline">{file.status}</Badge>
        <span className="text-muted-foreground text-xs">
          Diff could not be displayed.
        </span>
        {file.blobUrl && (
          <a
            href={file.blobUrl}
            target="_blank"
            rel="noreferrer"
            className="text-xs underline"
          >
            View blob
          </a>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Isolates one file's diff render: a `PatchDiff` parse/render throw must
 * degrade to a single fallback row, never unmount the whole Files tab
 * through the route-level error boundary.
 */
class FileDiffErrorBoundary extends Component<
  { file: PRFileItem; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  render(): ReactNode {
    if (this.state.failed) return <UnparsableDiffFallback file={this.props.file} />;
    return this.props.children;
  }
}

export function FilesChangedTab({ owner, repo, number }: FilesProps) {
  const [view, setView] = useState<DiffView>("unified");
  const { mode } = useTheme();
  const filesQuery = usePullFilesAll(owner, repo, number);
  const sentinelQuery = usePullSentinel(owner, repo, number);

  const options = useMemo<FileDiffOptions<SentinelAnnotationMeta, undefined>>(
    () => ({
      theme: { dark: "pierre-dark", light: "pierre-light" },
      themeType: mode,
      diffStyle: view,
    }),
    [mode, view],
  );

  const commentsByFile = useMemo(() => {
    const map = new Map<string, SentinelComment[]>();
    for (const c of sentinelQuery.data?.comments ?? []) {
      const list = map.get(c.fileName) ?? [];
      list.push(c);
      map.set(c.fileName, list);
    }
    return map;
  }, [sentinelQuery.data]);

  if (filesQuery.isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-48 w-full" />
        ))}
      </div>
    );
  }

  if (filesQuery.isError || !filesQuery.data) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">Failed to load changed files.</p>
        <Button variant="outline" className="mt-3" onClick={() => filesQuery.refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (filesQuery.data.length === 0) {
    return (
      <div className="rounded-lg border p-6 text-center">
        <p className="text-muted-foreground text-sm">No changed files.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-muted-foreground text-xs">
          {filesQuery.data.length} files changed
        </p>
        <ButtonGroup>
          <Button
            size="sm"
            variant={view === "unified" ? "default" : "outline"}
            onClick={() => setView("unified")}
          >
            Unified
          </Button>
          <Button
            size="sm"
            variant={view === "split" ? "default" : "outline"}
            onClick={() => setView("split")}
          >
            Split
          </Button>
        </ButtonGroup>
      </div>
      {filesQuery.data.map((file) => (
        <FileDiffCard
          key={file.filename}
          file={file}
          options={options}
          comments={commentsByFile.get(file.filename) ?? []}
        />
      ))}
    </div>
  );
}

function FileDiffCard({
  file,
  options,
  comments,
}: {
  file: PRFileItem;
  options: FileDiffOptions<SentinelAnnotationMeta, undefined>;
  comments: SentinelComment[];
}) {
  const annotations = useMemo<DiffLineAnnotation<SentinelAnnotationMeta>[]>(
    () =>
      comments.map((c) => ({
        side: c.side === "LEFT" ? "deletions" : "additions",
        lineNumber: c.toLine,
        metadata: {
          commentId: c.id,
          severity: c.severity,
          comment: c.comment,
          fromLine: c.fromLine,
          toLine: c.toLine,
        },
      })),
    [comments],
  );

  const severityCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const c of comments) counts.set(c.severity, (counts.get(c.severity) ?? 0) + 1);
    return Array.from(counts.entries());
  }, [comments]);

  const fullPatch = useMemo(() => toFullPatch(file), [file]);

  if (!fullPatch) {
    return (
      <Card id={diffAnchor(file.filename)} className="scroll-mt-20">
        <CardContent className="flex flex-wrap items-center gap-2 pt-4 text-sm">
          <span className="font-mono text-xs font-medium">{file.filename}</span>
          <Badge variant="outline">{file.status}</Badge>
          <span className="text-muted-foreground text-xs">
            Binary or diff too large to display.
          </span>
          {file.blobUrl && (
            <a
              href={file.blobUrl}
              target="_blank"
              rel="noreferrer"
              className="text-xs underline"
            >
              View blob
            </a>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <div id={diffAnchor(file.filename)} className="scroll-mt-20">
      <FileDiffErrorBoundary file={file}>
        <PatchDiff<SentinelAnnotationMeta>
          patch={fullPatch}
        options={options}
        lineAnnotations={annotations}
        renderAnnotation={(annotation) => (
          <div className="flex flex-col gap-2 p-2">
            <div className="flex items-center gap-2">
              <Badge className={SEVERITY_STYLES[annotation.metadata.severity] ?? ""}>
                {severityLabel(annotation.metadata.severity)}
              </Badge>
              <span className="font-mono text-xs text-sky-600 dark:text-sky-400">
                L{annotation.metadata.fromLine}
                {annotation.metadata.toLine !== annotation.metadata.fromLine
                  ? `–L${annotation.metadata.toLine}`
                  : ""}
              </span>
            </div>
            <Markdown body={annotation.metadata.comment} />
          </div>
        )}
        renderHeaderFilenameSuffix={() =>
          severityCounts.length > 0 ? (
            <span className="flex items-center gap-1">
              {severityCounts.map(([severity, count]) => (
                <Badge key={severity} className={SEVERITY_STYLES[severity] ?? ""}>
                  {severityLabel(severity)} · {count}
                </Badge>
              ))}
            </span>
          ) : null
        }
        renderHeaderMetadata={() =>
          comments.length > 0 ? <span>{comments.length} comments</span> : null
        }
        />
      </FileDiffErrorBoundary>
    </div>
  );
}
