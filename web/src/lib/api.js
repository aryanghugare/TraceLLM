import { parseSseStream } from "./sse";

const API_BASE = import.meta.env.VITE_API_BASE || "";

async function safeJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return null;
  }
}

export async function fetchSessions() {
  const response = await fetch(`${API_BASE}/api/sessions`);
  const data = await safeJson(response);

  if (!response.ok) {
    throw new Error(data?.error || "Failed to load sessions");
  }

  return data || { sessions: [] };
}

export async function fetchSession(sessionId) {
  const response = await fetch(
    `${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`
  );
  const data = await safeJson(response);

  if (!response.ok) {
    throw new Error(data?.error || "Failed to load session");
  }

  return data || { messages: [] };
}

export async function fetchAnalytics() {
  const response = await fetch(`${API_BASE}/api/analytics`);
  const data = await safeJson(response);

  if (!response.ok) {
    throw new Error(data?.error || "Failed to load analytics");
  }

  return data || {};
}

export async function streamChat(payload, { signal } = {}) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const data = await safeJson(response);
    throw new Error(data?.error || "Failed to start stream");
  }

  if (!response.body) {
    throw new Error("Streaming not supported by the browser");
  }

  return parseSseStream(response.body);
}
