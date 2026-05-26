function formatTitle(title, sessionId) {
  if (title && title.trim()) {
    return title.trim();
  }

  if (sessionId) {
    return `Session ${sessionId.slice(0, 6)}`;
  }

  return "Untitled session";
}

function formatDate(value) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleDateString();
}

function Sidebar({
  sessions,
  activeSessionId,
  isLoading,
  onSelect,
  onNewSession,
  onRefresh,
}) {
  return (
    <aside className="panel flex w-full flex-col gap-4 px-4 py-5 md:w-72">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg">Conversations</h2>
          <p className="text-xs text-muted">Resume or start new chats.</p>
        </div>
        <button
          type="button"
          className="glass-button"
          onClick={onRefresh}
          disabled={isLoading}
        >
          {isLoading ? "Loading" : "Refresh"}
        </button>
      </div>

      <button
        type="button"
        onClick={onNewSession}
        className="rounded-xl bg-accent/20 px-3 py-2 text-sm font-semibold text-accent transition hover:bg-accent/30"
      >
        New chat
      </button>

      <div className="flex-1 space-y-2 overflow-y-auto pr-1">
        {sessions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/60 px-3 py-4 text-xs text-muted">
            No sessions yet. Start a chat to create one.
          </div>
        ) : (
          sessions.map((session) => {
            const isActive = session.sessionId === activeSessionId;
            return (
              <button
                key={session.sessionId}
                type="button"
                onClick={() => onSelect(session.sessionId)}
                className={
                  isActive
                    ? "w-full rounded-xl border border-accent/40 bg-accent/15 px-3 py-3 text-left shadow-glow"
                    : "w-full rounded-xl border border-border/60 bg-surface/70 px-3 py-3 text-left transition hover:bg-surface-strong/80"
                }
              >
                <div className="text-sm font-semibold text-text">
                  {formatTitle(session.title, session.sessionId)}
                </div>
                <div className="mt-1 text-xs text-muted">
                  {formatDate(session.updatedAt) || ""}
                </div>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}

export default Sidebar;
