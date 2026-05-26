import { useEffect, useRef } from "react";

import MessageBubble from "./MessageBubble";

function ChatWindow({ messages, isStreaming, isLoading, sessionId }) {
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isStreaming]);

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 py-10 text-center text-sm text-muted">
        Select a session or start a new chat to begin.
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-5 py-6">
      {isLoading ? (
        <div className="rounded-xl border border-dashed border-border/60 px-4 py-6 text-sm text-muted">
          Loading conversation history...
        </div>
      ) : messages.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border/60 px-4 py-6 text-sm text-muted">
          No messages yet. Send the first prompt to start the stream.
        </div>
      ) : (
        messages.map((message) => (
          <MessageBubble
            key={message.id}
            role={message.role}
            content={message.content}
          />
        ))
      )}

      {isStreaming ? (
        <div className="text-xs text-muted">Streaming response...</div>
      ) : null}

      <div ref={bottomRef} />
    </div>
  );
}

export default ChatWindow;
