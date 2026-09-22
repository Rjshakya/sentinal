import React, { useCallback, useMemo, useState } from "react";
import { parsePatchFiles, type ParsedPatch } from "@pierre/diffs";
import {
  CodeView,
  type CodeViewHandle,
  type CodeViewItem,
  type CodeViewReactOptions,
  type DiffLineAnnotation,
  type FileDiffMetadata,
} from "@pierre/diffs/react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useTheme } from "@/components/theme-provider";
import type { PRFileItem, ReviewCommentItem } from "@/lib/api";
import { usePullConversation, usePullFilesAll } from "@/lib/pulls";
import { SEVERITY_STYLES, severityLabel } from "@/lib/pull-utils";
import { Skeleton } from "@/components/ui/skeleton";

import { DiffCommentCard, type DiffCommentSide } from "./-diff-comment-card";
import { IconMessage, IconMessageCircle } from "@tabler/icons-react";

type FilesProps = {
  owner: string;
  repo: string;
  number: number;
};

/**
 * Unified annotation metadata for every diff comment, whatever the author:
 * Sentinel findings (carry `severity`) and GitHub review comments from any
 * person or bot (no severity). `renderAnnotation` maps this 1:1 onto
 * {@link DiffCommentCard}.
 */
type DiffCommentMeta = {
  authorLogin: string;
  authorAvatar?: string | null;
  createdAt?: string | null;
  body: string;
  fromLine: number;
  toLine: number;
  side: DiffCommentSide;
  severity?: string | null;
};

type DiffView = "unified" | "split";

function diffAnchor(filename: string): string {
  return `diff-${filename}`;
}

function codeViewItemId(filename: string): string {
  return `diff:${filename}`;
}

let codeViewHandle: CodeViewHandle<DiffCommentMeta, undefined> | null = null;

export function scrollToDiffFile(filename: string): void {
  const id = codeViewItemId(filename);
  const handle = codeViewHandle;
  if (handle?.getItem(id) !== undefined) {
    handle.scrollTo({ type: "item", id, align: "start", behavior: "smooth" });
    return;
  }
  document
    .getElementById(diffAnchor(filename))
    ?.scrollIntoView({ behavior: "smooth", block: "start" });
}

/**
 * Rebuild a complete unified-diff document around GitHub's hunk-only
 * `patch` block.
 *
 * `GET /pulls/{n}/files` returns `patch` starting directly at the first
 * `@@` hunk, with no `---`/`+++` file headers — but `parsePatchFiles`
 * splits input into per-file blobs on file boundaries and throws
 * ("must contain exactly 1 file diff") when the input yields zero files.
 * The backend passes GitHub's payload through verbatim, so the envelope
 * is reconstructed here from the file's `status` (+ `previousFilename`
 * for renames).
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

function NoDiffFallback({ file, message }: { file: PRFileItem; message: string }) {
  return (
    <Card id={diffAnchor(file.filename)} className="scroll-mt-20">
      <CardContent className="flex flex-wrap items-center gap-2 pt-4 text-sm">
        <span className="font-mono text-xs font-medium">{file.filename}</span>
        <Badge variant="outline">{file.status}</Badge>
        <span className="text-muted-foreground text-xs">{message}</span>
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
 * Recover a Sentinel severity from the badge image our backend stamps on
 * posted bodies (`app/utils/severity_badge.py`). Plain human/bot comments
 * carry no badge → null → no severity badge on the card.
 */
const BADGE_SEVERITY: Record<string, string> = {
  "p1.png": "P1_CRITICAL",
  "p2.png": "P2_WARNING",
  "p3.png": "P3_NITPICK",
};

function severityFromBody(body: string): string | null {
  const match = body.match(/sentinal-pr-badges\/(p1|p2|p3)\.png/);
  return match ? (BADGE_SEVERITY[match[1]] ?? null) : null;
}

function reviewCommentToMeta(c: ReviewCommentItem): DiffCommentMeta | null {
  if (c.line == null) return null;
  return {
    authorLogin: c.authorLogin,
    authorAvatar: c.authorAvatar,
    createdAt: c.createdAt,
    body: c.body,
    fromLine: c.line,
    toLine: c.line,
    side: c.side === "LEFT" ? "LEFT" : "RIGHT",
    severity: severityFromBody(c.body),
  };
}

/**
 * Diff comments are GitHub review comments, full stop: whatever the post
 * step published (ours, other bots, humans). A run whose post failed has
 * nothing on GitHub and therefore shows nothing here.
 */
/**
 * Deterministic content version for a file's annotations. CodeView only
 * syncs a reused item record when `version` changes (`syncItemRecord`), so
 * annotations arriving after first mount (conversation resolving after
 * files) would otherwise never render. Any content change alters the hash.
 */
function annotationSignature(metas: DiffCommentMeta[]): string {
  return metas
    .map((m) => `${m.toLine}::${m.side}::${m.authorLogin}::${m.body}`)
    .join("\n");
}

function hashString(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) | 0;
  return h;
}

function toAnnotation(meta: DiffCommentMeta, line: number): DiffLineAnnotation<DiffCommentMeta> {
  return {
    side: meta.side === "LEFT" ? "deletions" : "additions",
    lineNumber: line,
    metadata: meta,
  };
}

function countSeverities(metas: DiffCommentMeta[]): [string, number][] {
  const counts = new Map<string, number>();
  for (const m of metas) {
    if (m.severity) counts.set(m.severity, (counts.get(m.severity) ?? 0) + 1);
  }
  return Array.from(counts.entries());
}

export function FilesChangedTab({ owner, repo, number }: FilesProps) {
  const [view] = useState<DiffView>("unified");
  const { mode } = useTheme();
  const filesQuery = usePullFilesAll(owner, repo, number);
  const conversationQuery = usePullConversation(owner, repo, number);

  const options = useMemo<CodeViewReactOptions<DiffCommentMeta, undefined>>(
    () => ({
      theme: { dark: "pierre-dark", light: "pierre-light" },
      themeType: mode,
      diffStyle: view,
      stickyHeaders: true,
      enableLineSelection: true,
    }),
    [mode, view],
  );

  const reviewCommentsByFile = useMemo(() => {
    const map = new Map<string, ReviewCommentItem[]>();
    for (const c of conversationQuery.data?.reviewComments ?? []) {
      const list = map.get(c.path) ?? [];
      list.push(c);
      map.set(c.path, list);
    }
    return map;
  }, [conversationQuery.data]);

  /**
   * Per-file comment metas, straight from GitHub review comments — the single
   * source of truth. Sorted oldest first.
   */
  const metasByFile = useMemo(() => {
    const map = new Map<string, DiffCommentMeta[]>();
    for (const [path, list] of reviewCommentsByFile) {
      const metas: DiffCommentMeta[] = [];
      for (const rc of list) {
        const meta = reviewCommentToMeta(rc);
        if (meta) metas.push(meta);
      }
      if (metas.length > 0) {
        metas.sort((a, b) => (a.createdAt ?? "").localeCompare(b.createdAt ?? ""));
        map.set(path, metas);
      }
    }
    return map;
  }, [reviewCommentsByFile]);

  const commentsByItemId = useMemo(() => {
    const map = new Map<string, DiffCommentMeta[]>();
    for (const [filename, list] of metasByFile) {
      map.set(codeViewItemId(filename), list);
    }
    return map;
  }, [metasByFile]);

  const { items, failedFiles, binaryFiles } = useMemo(() => {
    const items: CodeViewItem<DiffCommentMeta>[] = [];
    const failedFiles: PRFileItem[] = [];
    const binaryFiles: PRFileItem[] = [];
    for (const file of filesQuery.data ?? []) {
      const fullPatch = toFullPatch(file);
      if (!fullPatch) {
        // Pure rename (no content change): GitHub sends no patch, and there
        // is nothing to review — render no card at all.
        const status = file.status.toLowerCase();
        if (status === "renamed" || status === "copied") continue;
        binaryFiles.push(file);
        continue;
      }
      let parsed: ParsedPatch[];
      try {
        parsed = parsePatchFiles(fullPatch);
      } catch {
        failedFiles.push(file);
        continue;
      }
      const fileDiff: FileDiffMetadata | undefined = parsed.flatMap((p) => p.files)[0];
      if (!fileDiff) {
        failedFiles.push(file);
        continue;
      }
      const metas = metasByFile.get(file.filename) ?? [];
      items.push({
        id: codeViewItemId(file.filename),
        type: "diff",
        fileDiff,
        version: hashString(annotationSignature(metas)),
        annotations: metas.map((meta) => toAnnotation(meta, meta.toLine)),
      });
    }
    return { items, failedFiles, binaryFiles };
  }, [filesQuery.data, metasByFile]);

  const attachViewer = useCallback(
    (handle: CodeViewHandle<DiffCommentMeta, undefined> | null) => {
      codeViewHandle = handle;
    },
    [],
  );

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
      {binaryFiles.map((file) => (
        <NoDiffFallback
          key={file.filename}
          file={file}
          message="Binary or diff too large to display."
        />
      ))}
      {failedFiles.map((file) => (
        <NoDiffFallback
          key={file.filename}
          file={file}
          message="Diff could not be displayed."
        />
      ))}
      {items.length > 0 && (
        <CodeView<DiffCommentMeta>
          items={items}
          options={options}
          ref={attachViewer}
          className="h-[96vh] overflow-auto border font-sans   "
          style={{
            '--diffs-font-family': "var(--font-mono)",
            '--diffs-font-size': "12px",
          } as React.CSSProperties}
          renderAnnotation={(annotation) => (
            <DiffCommentCard
              authorLogin={annotation.metadata.authorLogin}
              authorAvatar={annotation.metadata.authorAvatar}
              createdAt={annotation.metadata.createdAt}
              body={annotation.metadata.body}
              fromLine={annotation.metadata.fromLine}
              toLine={annotation.metadata.toLine}
              side={annotation.metadata.side}
              severity={annotation.metadata.severity}
            />
          )}
          renderHeaderFilenameSuffix={(item) => {
            const counts = countSeverities(commentsByItemId.get(item.id) ?? []);
            return counts.length > 0 ? (
              <span className="flex items-center gap-1">
                {counts.map(([severity, count]) => (
                  <Badge key={severity} className={SEVERITY_STYLES[severity] ?? ""}>
                    {severityLabel(severity)} · {count}
                  </Badge>
                ))}
              </span>
            ) : null;
          }}
          renderHeaderMetadata={(item) => {
            const list = commentsByItemId.get(item.id) ?? [];
            return list.length > 0 ? <span className="flex items-center gap-1 ml-2">
              <IconMessage className="size-4" />
              <p>
                {list.length}
              </p>

            </span> : null;
          }}
        />
      )}
    </div>
  );
}
