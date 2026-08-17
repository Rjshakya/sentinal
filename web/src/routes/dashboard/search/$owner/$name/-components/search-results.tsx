import { useTheme } from "@/components/theme-provider";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { CodeSearchResult } from "@/lib/api";
import { CodeBlock } from "./code-block";
import React from "react";

export const SearchResults = React.memo(
  ({ results, owner, repo }: { results: CodeSearchResult[]; owner: string; repo: string }) => {
    const theme = useTheme().mode;

    if (results.length === 0) {
      return (
        <p className="text-muted-foreground text-xs">
          No matches in {owner}/{repo}.
        </p>
      );
    }

    return (
      <div className="space-y-2 ">
        <ScrollArea className="max-h-112 overflow-y-auto">
          <ul className="flex flex-col gap-1 rounded-md ">
            {results.map((result, idx) => (
              <li
                key={`${result.file_name}-${result.start_line}-${idx}`}
                className="space-y-2 p-3 bg-background  "
              >
                <div className="border-b border-ring/70  pb-2   flex flex-wrap items-center justify-between gap-2">
                  <span className="truncate font-medium  ">{result.file_name}</span>
                  <span className="font-mono">
                    {result.start_line}-{result.end_line}
                  </span>
                </div>
                <div className=" overflow-x-scroll overflow-y-auto  p-0 text-xs">
                  <CodeBlock
                    language={result.language}
                    code={result.content}
                    theme={theme === "dark" ? "dark" : "light"}
                  />
                </div>
              </li>
            ))}
          </ul>
        </ScrollArea>
      </div>
    );
  },
);
