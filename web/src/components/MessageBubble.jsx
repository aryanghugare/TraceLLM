import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function MessageBubble({ role, content }) {
  const isAssistant = role === "assistant";

  return (
    <div className={`flex ${isAssistant ? "justify-start" : "justify-end"}`}>
      <div
        className={
          isAssistant
            ? "w-full max-w-2xl rounded-2xl border border-border/60 bg-surface-strong/80 px-4 py-3 shadow-glow"
            : "w-full max-w-2xl rounded-2xl border border-accent/40 bg-accent/15 px-4 py-3 text-text"
        }
      >
        <div className="mb-2 text-[11px] uppercase tracking-[0.25em] text-muted">
          {isAssistant ? "Assistant" : "User"}
        </div>
        {isAssistant ? (
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            className="prose prose-sm prose-invert max-w-none"
          >
            {content || ""}
          </ReactMarkdown>
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{content}</p>
        )}
      </div>
    </div>
  );
}

export default MessageBubble;
