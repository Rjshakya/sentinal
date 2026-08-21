### web/src/routes/dashboard/search/$owner/$name/-components/code-block.tsx

```diff

deleted file mode 100644
index 9a56a4b..0000000
--- a/web/src/routes/dashboard/search/$owner/$name/-components/code-block.tsx
+++ /dev/null
@@ -1,24 +0,0 @@
    2       -import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
    3       -import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";
    4       -
    5       -export const CodeBlock = ({
    6       -  code,
    7       -  language,
    8       -  theme,
    9       -}: {
   10       -  code: string;
   11       -  language: string;
   12       -  theme: "dark" | "light";
   13       -}) => {
   14       -  return (
   15       -    <SyntaxHighlighter
   16       -      showLineNumbers={true}
   17       -      wrapLongLines={true}
   18       -      language={language}
   19       -      style={theme === "dark" ? oneDark : oneLight}
   20       -      customStyle={{ background: theme === "dark" ? "#0A0A0A" : "#FFFFFF" }}
   21       -    >
   22       -      {code}
   23       -    </SyntaxHighlighter>
   24       -  );
   25       -};

```
