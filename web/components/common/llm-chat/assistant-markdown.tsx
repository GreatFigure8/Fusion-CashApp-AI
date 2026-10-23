import Markdown, { type Components } from "react-markdown";
import rehypeSanitize, { defaultSchema, type Options } from "rehype-sanitize";

// The default allow-list without images: no remote loads from model output. No rehype-raw, so raw
// HTML in the text is never parsed as HTML.
const sanitizeSchema: Options = {
  ...defaultSchema,
  tagNames: (defaultSchema.tagNames ?? []).filter((tag) => tag !== "img"),
};

const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2">
      {children}
    </a>
  ),
};

export function AssistantMarkdown({ children }: { children: string }) {
  return (
    <div className="text-sm leading-relaxed break-words [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown rehypePlugins={[[rehypeSanitize, sanitizeSchema]]} components={components}>
        {children}
      </Markdown>
    </div>
  );
}
