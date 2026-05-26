const express = require("express");

const Session = require("../models/Session");
const Log = require("../models/Log");
const { createLlmWrapper } = require("../llmWrapper");

const router = express.Router();

function resolveProvider(input) {
  return String(input || process.env.LLM_PROVIDER || "openai").toLowerCase();
}

function resolveApiKey(provider, apiKeyOverride) {
  if (apiKeyOverride) {
    return apiKeyOverride;
  }

  switch (provider) {
    case "openai":
      return process.env.OPENAI_API_KEY;
    case "gemini":
      return process.env.GEMINI_API_KEY;
    case "anthropic":
      return process.env.ANTHROPIC_API_KEY;
    default:
      return undefined;
  }
}

function toNumber(value) {
  if (value === undefined || value === null || value === "") {
    return undefined;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

router.get("/api/sessions", async (req, res, next) => {
  try {
    const sessions = await Session.find({})
      .sort({ updatedAt: -1 })
      .lean();

    res.json({ sessions });
  } catch (error) {
    next(error);
  }
});

router.get("/api/sessions/:id", async (req, res, next) => {
  try {
    const sessionId = req.params.id;
    const session = await Session.findOne({ sessionId }).lean();
    const messages = await Log.find({ sessionId })
      .sort({ createdAt: 1 })
      .lean();

    res.json({ session, messages });
  } catch (error) {
    next(error);
  }
});

router.post("/api/chat", async (req, res, next) => {
  const body = req.body || {};
  const sessionId = body.sessionId;
  const message = typeof body.message === "string" ? body.message.trim() : "";

  if (!sessionId || !message) {
    return res
      .status(400)
      .json({ error: "sessionId and message are required" });
  }

  const provider = resolveProvider(body.provider);
  const apiKey = resolveApiKey(provider, body.apiKey);

  if (!apiKey) {
    return res.status(400).json({
      error: "Missing API key for provider",
      provider,
    });
  }

  const temperature = toNumber(body.temperature);
  const maxTokens = toNumber(body.maxTokens);

  try {
    const existingSession = await Session.findOne({ sessionId });

    if (!existingSession) {
      await Session.create({
        sessionId,
        title: typeof body.title === "string" ? body.title.trim() : "",
      });
    } else if (typeof body.title === "string" && body.title.trim()) {
      existingSession.title = body.title.trim();
      await existingSession.save();
    }

    const recentLogs = await Log.find({ sessionId })
      .sort({ createdAt: -1 })
      .limit(5)
      .lean();
    const history = recentLogs
      .reverse()
      .map((entry) => ({ role: entry.role, content: entry.content }));

    await Log.create({ sessionId, role: "user", content: message });

    const streamMessages = [...history, { role: "user", content: message }];
    const llm = createLlmWrapper({
      provider,
      apiKey,
      model: body.model,
    });

    res.status(200);
    res.setHeader("Content-Type", "text/event-stream");
    res.setHeader("Cache-Control", "no-cache, no-transform");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("X-Accel-Buffering", "no");

    if (typeof res.flushHeaders === "function") {
      res.flushHeaders();
    }

    const abortController = new AbortController();

    req.on("close", () => {
      abortController.abort();
    });

    try {
      for await (const chunk of llm.streamChat({
        messages: streamMessages,
        model: body.model,
        temperature,
        maxTokens,
        sessionId,
        signal: abortController.signal,
      })) {
        if (abortController.signal.aborted) {
          break;
        }

        res.write(`data: ${JSON.stringify({ delta: chunk })}\n\n`);
      }

      if (!abortController.signal.aborted) {
        res.write(`data: ${JSON.stringify({ done: true })}\n\n`);
      }
    } catch (error) {
      if (!abortController.signal.aborted) {
        res.write(
          `event: error\ndata: ${JSON.stringify({ message: error.message })}\n\n`
        );
      }
    } finally {
      res.end();
    }
  } catch (error) {
    next(error);
  }
});

module.exports = router;
