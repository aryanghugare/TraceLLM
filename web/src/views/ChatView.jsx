import { useEffect, useMemo, useState } from "react";

import ChatWindow from "../components/ChatWindow";
import ChatInput from "../components/ChatInput";
import { fetchSession, streamChat } from "../lib/api";

function createMessageId(prefix) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}`;
}

function ChatView({ sessionId, sessionTitle, isDraft, onSessionRefresh }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [abortController, setAbortController] = useState(null);

  useEffect(() => {
    let ignore = false;

    const loadHistory = async () => {
      if (!sessionId) {
        setMessages([]);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const data = await fetchSession(sessionId);
        if (ignore) {
          return;
        }

        const history = (data?.messages || []).map((entry) => ({
          id: entry._id || createMessageId(entry.role),
          role: entry.role,
          content: entry.content,
        }));

        setMessages(history);
      } catch (loadError) {
        if (!ignore) {
          setError(loadError.message || "Failed to load session");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    };

    loadHistory();

    return () => {
      ignore = true;
    };
  }, [sessionId]);

  const sessionLabel = useMemo(() => {
    if (sessionTitle && sessionTitle.trim()) {
      return sessionTitle.trim();
    }

    if (sessionId) {
      return `Session ${sessionId.slice(0, 8)}`;
    }

    return "New conversation";
  }, [sessionId, sessionTitle]);

  const handleSend = async () => {
    if (!sessionId || isStreaming || !input.trim()) {
      return;
    }

    const message = input.trim();
    const assistantId = createMessageId("assistant");

    setInput("");
    setError(null);
    setMessages((prev) => [
      ...prev,
      { id: createMessageId("user"), role: "user", content: message },
      { id: assistantId, role: "assistant", content: "" },
    ]);

    const controller = new AbortController();
    setAbortController(controller);
    setIsStreaming(true);

    try {
      const payload = {
        sessionId,
        message,
      };

      if (isDraft) {
        payload.title = message.slice(0, 48);
      }

      const stream = await streamChat(payload, { signal: controller.signal });

      for await (const event of stream) {
        if (controller.signal.aborted) {
          break;
        }

        if (event.event === "error") {
          setError(event.data?.message || "Streaming error");
          break;
        }

        if (event.data?.delta) {
          const delta = String(event.data.delta);
          setMessages((prev) =>
            prev.map((item) =>
              item.id === assistantId
                ? { ...item, content: item.content + delta }
                : item
            )
          );
        }

        if (event.data?.done) {
          break;
        }
      }
    } catch (streamError) {
      if (!controller.signal.aborted) {
        setError(streamError.message || "Streaming failed");
      }
    } finally {
      setIsStreaming(false);
      setAbortController(null);
      onSessionRefresh?.();
    }
  };

  const handleCancel = () => {
    if (abortController) {
      abortController.abort();
    }
  };

  return (
    <section className="panel flex min-h-[70vh] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 px-5 py-4">
        <div>
          <div className="text-xs uppercase tracking-[0.3em] text-muted">
            Active session
          </div>
          <div className="font-display text-xl text-text">{sessionLabel}</div>
          {sessionId ? (
            <div className="text-xs text-muted">{sessionId}</div>
          ) : null}
        </div>
        {error ? (
          <div className="rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-xs text-accent">
            {error}
          </div>
        ) : null}
      </div>

      <ChatWindow
        messages={messages}
        isStreaming={isStreaming}
        isLoading={isLoading}
        sessionId={sessionId}
      />

      <ChatInput
        value={input}
        onChange={setInput}
        onSend={handleSend}
        onCancel={handleCancel}
        isStreaming={isStreaming}
        disabled={!sessionId}
      />
    </section>
  );
}

export default ChatView;
