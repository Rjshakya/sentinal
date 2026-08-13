import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark, oneLight } from "react-syntax-highlighter/dist/esm/styles/prism";

export const CodeBlock = ({
  code,
  language,
  theme,
}: {
  code: string;
  language: string;
  theme: "dark" | "light";
}) => {
  return (
    <SyntaxHighlighter
      showLineNumbers={true}
      wrapLongLines={true}
      language={language}
      style={theme === "dark" ? oneDark : oneLight}
      customStyle={{ background: theme === "dark" ? "#0A0A0A" : "#FFFFFF" }}
    >
      {code}
    </SyntaxHighlighter>
  );
};
