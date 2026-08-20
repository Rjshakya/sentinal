### web/src/routes/dashboard/search/$owner/$name/-components/search-results.tsx

```diff

deleted file mode 100644
index 0f1080c..0000000
--- a/web/src/routes/dashboard/search/$owner/$name/-components/search-results.tsx
+++ /dev/null
@@ -1,48 +0,0 @@
    2       -import { useTheme } from "@/components/theme-provider";
    3       -import { ScrollArea } from "@/components/ui/scroll-area";
    4       -import type { CodeSearchResult } from "@/lib/api";
    5       -import { CodeBlock } from "./code-block";
    6       -import React from "react";
    7       -
    8       -export const SearchResults = React.memo(
    9       -  ({ results, owner, repo }: { results: CodeSearchResult[]; owner: string; repo: string }) => {
   10       -    const theme = useTheme().mode;
   11       -
   12       -    if (results.length === 0) {
   13       -      return (
   14       -        <p className="text-muted-foreground text-xs">
   15       -          No matches in {owner}/{repo}.
   16       -        </p>
   17       -      );
   18       -    }
   19       -
   20       -    return (
   21       -      <div className="space-y-2 ">
   22       -        <ScrollArea className="max-h-112 overflow-y-auto">
   23       -          <ul className="flex flex-col gap-1 rounded-md ">
   24       -            {results.map((result, idx) => (
   25       -              <li
   26       -                key={`${result.file_name}-${result.start_line}-${idx}`}
   27       -                className="space-y-2 p-3 bg-background  "
   28       -              >
   29       -                <div className="border-b border-ring/70  pb-2   flex flex-wrap items-center justify-between gap-2">
   30       -                  <span className="truncate font-medium  ">{result.file_name}</span>
   31       -                  <span className="font-mono">
   32       -                    {result.start_line}-{result.end_line}
   33       -                  </span>
   34       -                </div>
   35       -                <div className=" overflow-x-scroll overflow-y-auto  p-0 text-xs">
   36       -                  <CodeBlock
   37       -                    language={result.language}
   38       -                    code={result.content}
   39       -                    theme={theme === "dark" ? "dark" : "light"}
   40       -                  />
   41       -                </div>
   42       -              </li>
   43       -            ))}
   44       -          </ul>
   45       -        </ScrollArea>
   46       -      </div>
   47       -    );
   48       -  },
   49       -);

```
