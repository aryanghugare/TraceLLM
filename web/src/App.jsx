import { useCallback, useEffect, useMemo, useState } from "react";

import Sidebar from "./components/Sidebar";
import ChatView from "./views/ChatView";
import DashboardView from "./views/DashboardView";
import { fetchSessions } from "./lib/api";

function App() {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [view, setView] = useState("chat");
  const [loadingSessions, setLoadingSessions] = useState(false);

  const refreshSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const data = await fetchSessions();
      const list = data?.sessions || [];
      setSessions(list);
      setActiveSessionId((current) =>
        current || (list[0] ? list[0].sessionId : null)
      );
    } catch (error) {
      console.error("Failed to load sessions", error);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    refreshSessions();
  }, [refreshSessions]);

  const activeSession = useMemo(
    () =>
      sessions.find((session) => session.sessionId === activeSessionId) || null,
    [sessions, activeSessionId]
  );

  const isDraft = Boolean(activeSessionId && !activeSession);

  const handleNewSession = () => {
    const newId =
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `session-${Date.now()}`;
    setActiveSessionId(newId);
    setView("chat");
  };

  const toggleClass = (target) =>
    target === view
      ? "rounded-full bg-accent text-slate-900 px-4 py-2 text-sm font-semibold shadow-glow"
      : "rounded-full border border-border/70 bg-surface/70 px-4 py-2 text-sm font-medium text-text transition hover:bg-surface-strong/80";

  return (
    <div className="min-h-screen text-text">
      <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 p-4 md:flex-row md:p-6">
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          isLoading={loadingSessions}
          onSelect={setActiveSessionId}
          onNewSession={handleNewSession}
          onRefresh={refreshSessions}
        />
        <main className="flex flex-1 flex-col gap-4">
          <div className="panel-strong flex flex-col gap-4 px-5 py-4 md:flex-row md:items-center md:justify-between">
            <div>
              <span className="chip">TraceLLM</span>
              <h1 className="mt-3 font-display text-2xl md:text-3xl">
                Observability Console
              </h1>
              <p className="text-sm text-muted">
                Live chat streaming with analytics snapshots.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button type="button" onClick={() => setView("chat")} className={toggleClass("chat")}>
                Chat
              </button>
              <button type="button" onClick={() => setView("dashboard")} className={toggleClass("dashboard")}>
                Dashboard
              </button>
            </div>
          </div>

          {view === "chat" ? (
            <ChatView
              sessionId={activeSessionId}
              sessionTitle={activeSession?.title}
              isDraft={isDraft}
              onSessionRefresh={refreshSessions}
            />
          ) : (
            <DashboardView />
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
