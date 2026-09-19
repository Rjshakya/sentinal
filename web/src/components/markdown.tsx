import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Markdown({ body }: { body: string }) {
  if (!body || body.trim().length === 0) {
    return (
      <p className="text-muted-foreground text-sm italic">
        No description provided.
      </p>
    );
  }
  return (
    <div className="prose prose-sm dark:prose-invert max-w-none break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
    </div>
  );
}
