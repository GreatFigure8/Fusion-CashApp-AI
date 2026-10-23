import Markdown, { type Components } from "react-markdown";
import rehypeSanitize, { defaultSchema, type Options } from "rehype-sanitize";

// The default allow-list without images: no remote loads from model output. No rehype-raw, so raw
// HTML in the text is never parsed as HTML.
const sanitizeSchema: Options = {
  ...defaultSchema,
  tagNames: (defaultSchema.tagNames ?? []).filter((tag) => tag !== "img"),
};

/** Only http(s) and same-site relative links survive; anything else renders as plain text. */
function isSafeHref(href: string | undefined): href is string {
  if (!href) return false;
  if (href.startsWith("/") && !href.startsWith("//")) return true;
  return /^https?:\/\//i.test(href);
}

const components: Components = {
  a: ({ href, children }) =>
    isSafeHref(href) ? (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-acc underline underline-offset-2">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    ),
};

export function AssistantMarkdown({ children }: { children: string }) {
  return (
    <div className="text-[14px] leading-[1.7] break-words text-foreground [&_code]:rounded [&_code]:bg-surface-3 [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[12.5px] [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_pre]:my-2 [&_pre]:overflow-x-auto [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
      <Markdown rehypePlugins={[[rehypeSanitize, sanitizeSchema]]} components={components}>
        {children}
      </Markdown>
    </div>
  );
}
