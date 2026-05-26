const { Queue } = require("bullmq");

const PROVIDERS = new Set(["openai", "gemini", "anthropic"]);

let inferenceQueue;

function resolveRedisConnection(redis) {
  if (redis) {
    return redis;
  }

  if (process.env.REDIS_URL) {
    return { url: process.env.REDIS_URL };
  }

  const host = process.env.REDIS_HOST || "127.0.0.1";
  const port = process.env.REDIS_PORT ? Number(process.env.REDIS_PORT) : 6379;

  return { host, port };
}

function getInferenceQueue(redis) {
  if (!inferenceQueue) {
    inferenceQueue = new Queue("inference-logs", {
      connection: resolveRedisConnection(redis),
    });
  }

  return inferenceQueue;
}

function splitSystemMessages(messages) {
  const systemParts = [];
  const nonSystemMessages = [];

  for (const message of messages) {
    if (message.role === "system") {
      systemParts.push(message.content);
    } else {
      nonSystemMessages.push(message);
    }
  }

  return {
    system: systemParts.length ? systemParts.join("\n") : undefined,
    nonSystemMessages,
  };
}

function toGeminiContents(messages) {
  return messages.map((message) => ({
    role: message.role === "assistant" ? "model" : "user",
    parts: [{ text: String(message.content || "") }],
  }));
}

function buildLatency(ttfbMs, totalMs) {
  const latency = {};

  if (Number.isFinite(ttfbMs)) {
    latency.ttfbMs = ttfbMs;
  }

  if (Number.isFinite(totalMs)) {
    latency.totalMs = totalMs;
  }

  return Object.keys(latency).length ? latency : undefined;
}

function redactPii(text) {
  if (!text) {
    return text;
  }

  const emailRegex = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
  const phoneRegex =
    /\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b/g;
  const creditCardRegex = /\b(?:\d[ -]*?){13,19}\b/g;

  return text
    .replace(emailRegex, "[REDACTED]")
    .replace(phoneRegex, "[REDACTED]")
    .replace(creditCardRegex, "[REDACTED]");
}

function createProviderClient(provider, apiKey, clientOptions) {
  switch (provider) {
    case "openai": {
      const OpenAI = require("openai");
      return new OpenAI({ apiKey, ...clientOptions });
    }
    case "gemini": {
      const { GoogleGenerativeAI } = require("@google/generative-ai");
      return new GoogleGenerativeAI(apiKey);
    }
    case "anthropic": {
      const Anthropic = require("@anthropic-ai/sdk");
      return new Anthropic({ apiKey, ...clientOptions });
    }
    default:
      throw new Error(`Unsupported provider: ${provider}`);
  }
}

/**
 * @typedef {Object} LlmWrapperOptions
 * @property {"openai" | "gemini" | "anthropic"} provider
 * @property {string} apiKey
 * @property {string} [model]
 * @property {Object} [redis]
 * @property {Object} [clientOptions]
 */

/**
 * @typedef {Object} StreamChatParams
 * @property {Array<{role: "user" | "assistant" | "system", content: string}>} messages
 * @property {string} [model]
 * @property {number} [temperature]
 * @property {number} [maxTokens]
 * @property {string} [sessionId]
 * @property {AbortSignal} [signal]
 */

/**
 * Factory for provider-specific streaming.
 * @param {LlmWrapperOptions} options
 */
function createLlmWrapper(options) {
  const provider = String(options.provider || "").toLowerCase();

  if (!PROVIDERS.has(provider)) {
    throw new Error("Provider must be one of: openai, gemini, anthropic");
  }

  const client = createProviderClient(
    provider,
    options.apiKey,
    options.clientOptions || {}
  );
  const defaultModel = options.model;

  /**
   * Streams text chunks and enqueues a redacted final payload to BullMQ.
   * @param {StreamChatParams} params
   */
  async function* streamChat(params) {
    if (!Array.isArray(params.messages) || params.messages.length === 0) {
      throw new Error("messages must be a non-empty array");
    }

    const model = params.model || defaultModel;

    if (!model) {
      throw new Error("model is required");
    }

    const startedAt = Date.now();
    let ttfbMs;
    let tokenUsage;
    let status = "success";
    let accumulatedText = "";

    try {
      if (provider === "openai") {
        const stream = await client.chat.completions.create({
          model,
          messages: params.messages,
          temperature: params.temperature,
          max_tokens: params.maxTokens,
          stream: true,
          stream_options: { include_usage: true },
          signal: params.signal,
        });

        for await (const chunk of stream) {
          const delta = chunk.choices?.[0]?.delta?.content;

          if (delta) {
            if (ttfbMs === undefined) {
              ttfbMs = Date.now() - startedAt;
            }

            accumulatedText += delta;
            yield delta;
          }

          if (chunk.usage) {
            tokenUsage = {
              prompt: chunk.usage.prompt_tokens,
              completion: chunk.usage.completion_tokens,
              total: chunk.usage.total_tokens,
            };
          }
        }
      } else if (provider === "gemini") {
        const { system, nonSystemMessages } = splitSystemMessages(
          params.messages
        );
        const modelInstance = client.getGenerativeModel({
          model,
          systemInstruction: system,
        });
        const request = {
          contents: toGeminiContents(nonSystemMessages),
          generationConfig: {
            temperature: params.temperature,
            maxOutputTokens: params.maxTokens,
          },
        };

        const result = await modelInstance.generateContentStream(request);

        for await (const chunk of result.stream) {
          const text = chunk.text();

          if (text) {
            if (ttfbMs === undefined) {
              ttfbMs = Date.now() - startedAt;
            }

            accumulatedText += text;
            yield text;
          }
        }

        const finalResponse = await result.response;
        const usage = finalResponse.usageMetadata;

        if (usage) {
          tokenUsage = {
            prompt: usage.promptTokenCount,
            completion: usage.candidatesTokenCount,
            total: usage.totalTokenCount,
          };
        }
      } else if (provider === "anthropic") {
        const { system, nonSystemMessages } = splitSystemMessages(
          params.messages
        );
        const stream = await client.messages.create({
          model,
          messages: nonSystemMessages,
          system,
          temperature: params.temperature,
          max_tokens: params.maxTokens || 1024,
          stream: true,
        });

        for await (const event of stream) {
          if (event.type === "content_block_start") {
            const text = event.content_block?.text;

            if (text) {
              if (ttfbMs === undefined) {
                ttfbMs = Date.now() - startedAt;
              }

              accumulatedText += text;
              yield text;
            }
          }

          if (event.type === "content_block_delta") {
            const text = event.delta?.text;

            if (text) {
              if (ttfbMs === undefined) {
                ttfbMs = Date.now() - startedAt;
              }

              accumulatedText += text;
              yield text;
            }
          }

          if (event.type === "message_delta" && event.usage) {
            tokenUsage = {
              prompt: event.usage.input_tokens,
              completion: event.usage.output_tokens,
              total: event.usage.input_tokens + event.usage.output_tokens,
            };
          }

          if (event.type === "message_stop" && event.message?.usage) {
            tokenUsage = {
              prompt: event.message.usage.input_tokens,
              completion: event.message.usage.output_tokens,
              total:
                event.message.usage.input_tokens +
                event.message.usage.output_tokens,
            };
          }
        }
      }
    } catch (error) {
      status = "error";
      throw error;
    } finally {
      const totalMs = Date.now() - startedAt;
      const redactedText = redactPii(accumulatedText);
      const latency = buildLatency(ttfbMs, totalMs);
      const metadata = {
        provider,
        model,
        status,
      };

      if (latency) {
        metadata.latency = latency;
      }

      if (tokenUsage) {
        metadata.tokenUsage = tokenUsage;
      }

      const payload = {
        content: redactedText,
        metadata,
      };

      if (params.sessionId) {
        payload.sessionId = params.sessionId;
      }

      try {
        await getInferenceQueue(options.redis).add("inference-log", payload, {
          removeOnComplete: true,
          removeOnFail: true,
        });
      } catch (queueError) {
        console.error("Failed to enqueue inference log", queueError);
      }
    }
  }

  return { streamChat };
}

module.exports = {
  createLlmWrapper,
  redactPii,
};
