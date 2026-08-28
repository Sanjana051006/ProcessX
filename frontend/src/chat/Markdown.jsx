import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

/**
 * Assistant replies as rich text.
 *
 * GFM is the load-bearing plugin: this agent compares four interventions across
 * five columns, and a markdown table is the only sane way to say that. Syntax
 * highlighting matters for the same reason — it shows the SQL it ran, and an
 * unhighlighted query is a wall.
 *
 * Two overrides on top of the defaults. A `<pre>` gets a copy button, because
 * the SQL in it is the thing a person most wants to take away. A `<table>` gets
 * a scroll container, so a wide comparison scrolls inside itself instead of
 * pushing the whole conversation sideways.
 */
export default function Markdown({ children }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          pre: CodeBlock,
          table: ({ node, ...props }) => (
            <div className="table-scroll">
              <table {...props} />
            </div>
          ),
          a: ({ node, ...props }) => (
            <a target="_blank" rel="noreferrer noopener" {...props} />
          ),
        }}
      >
        {children || ""}
      </ReactMarkdown>
    </div>
  );
}

function CodeBlock({ children, ...props }) {
  const ref = useRef(null);
  const [copied, setCopied] = useState(false);

  async function copy() {
    const text = ref.current?.innerText ?? "";
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* a denied clipboard permission is not worth an error state */
    }
  }

  return (
    <div className="group relative">
      <button
        type="button"
        onClick={copy}
        className="absolute right-2 top-2 z-10 rounded-md border border-paper/20 bg-ink/80 px-2 py-1
                   font-mono text-[9.5px] uppercase tracking-[0.14em] text-paper/70 opacity-0
                   backdrop-blur transition hover:text-paper focus:opacity-100 group-hover:opacity-100"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <pre ref={ref} {...props}>
        {children}
      </pre>
    </div>
  );
}
