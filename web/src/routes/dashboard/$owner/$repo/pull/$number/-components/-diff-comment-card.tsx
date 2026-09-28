import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { CommonCard } from "@/components/common-card";
import { Markdown } from "@/components/markdown";
import { formatRelative, SEVERITY_STYLES, severityLabel } from "@/lib/pull-utils";

export type DiffCommentSide = "LEFT" | "RIGHT";

export type DiffCommentCardProps = {
  authorLogin: string;
  authorAvatar?: string | null;
  createdAt?: string | null;
  body: string;
  fromLine: number;
  toLine: number;
  side: DiffCommentSide;
  /** Sentinel findings carry a severity; plain GitHub comments omit it. */
  severity?: string | null;
};

const BADGE_MARKER = "sentinal-pr-badges"; // same marker as app/utils/severity_badge.py

/**
 * Our Markdown renderer doesn't execute raw HTML, so the severity badge
 * `<img>` line our backend prefixes would show up as literal text. We
 * already render severity as a proper Badge, so drop the tag line.
 */
function displayBody(body: string): string {
  const [first, ...rest] = body.split("\n");
  return first?.includes(BADGE_MARKER) ? rest.join("\n").trimStart() : body;
}

export function DiffCommentCard({
  authorLogin,
  authorAvatar,
  createdAt,
  body,
  severity,
}: DiffCommentCardProps) {
  const displayName = authorLogin.replace(/\[bot\]$/, "") || authorLogin;
  const initial = displayName.charAt(0).toUpperCase();

  return (
    <div className="p-2">
      <CommonCard
        className="max-w-xl mr-auto font-sans "
        header={
          <>
            <Avatar className="size-6">
              {authorAvatar && <AvatarImage src={authorAvatar} alt={authorLogin} />}
              <AvatarFallback>{initial}</AvatarFallback>
            </Avatar>
            <span className="text-sm font-sans  ">{displayName}</span>
            {severity && (
              <Badge className={SEVERITY_STYLES[severity] ?? ""}>
                {severityLabel(severity)}
              </Badge>
            )}
            {createdAt && (
              <span className="text-muted-foreground font-sans   ml-auto text-xs">
                {formatRelative(createdAt)}
              </span>
            )}
          </>
        }
        body={<Markdown body={displayBody(body)} />}
      />
    </div>
  );
}
