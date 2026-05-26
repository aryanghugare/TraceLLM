const mongoose = require("mongoose");
const { Queue, Worker } = require("bullmq");
const { z } = require("zod");

const Log = require("./models/Log");

const MAX_ATTEMPTS = 3;
const DEFAULT_CONCURRENCY = 5;

function resolveRedisConnection() {
  if (process.env.REDIS_URL) {
    return { url: process.env.REDIS_URL };
  }

  const host = process.env.REDIS_HOST || "127.0.0.1";
  const port = process.env.REDIS_PORT ? Number(process.env.REDIS_PORT) : 6379;

  return { host, port };
}

const logSchema = z
  .object({
    sessionId: z.string().min(1),
    content: z.string(),
    metadata: z
      .object({
        provider: z.enum(["openai", "gemini", "anthropic"]),
        model: z.string().min(1),
        status: z.enum(["success", "error"]),
        latency: z
          .object({
            ttfbMs: z.number().nonnegative(),
            totalMs: z.number().nonnegative(),
          })
          .strict(),
        tokenUsage: z
          .object({
            prompt: z.number().nonnegative(),
            completion: z.number().nonnegative(),
            total: z.number().nonnegative(),
          })
          .strict(),
      })
      .strict(),
  })
  .strict();

function sanitizePayload(data) {
  if (!data || typeof data !== "object") {
    return {};
  }

  const { __attempts, ...payload } = data;

  return payload;
}

function resolveMongoUri() {
  return process.env.MONGODB_URI || process.env.MONGO_URI;
}

function getAttemptCount(data) {
  if (!data || typeof data !== "object") {
    return 1;
  }

  const attempts = Number(data.__attempts);
  return Number.isFinite(attempts) && attempts > 0 ? attempts : 1;
}

async function startWorker() {
  const mongoUri = resolveMongoUri();

  if (!mongoUri) {
    throw new Error("Missing MONGODB_URI or MONGO_URI");
  }

  await mongoose.connect(mongoUri);

  const connection = resolveRedisConnection();
  const inferenceQueue = new Queue("inference-logs", { connection });
  const failedQueue = new Queue("failed-logs", { connection });

  const worker = new Worker(
    "inference-logs",
    async (job) => {
      const payload = sanitizePayload(job.data);
      const parsed = logSchema.parse(payload);

      await Log.create({
        sessionId: parsed.sessionId,
        role: "assistant",
        content: parsed.content,
        metadata: parsed.metadata,
      });
    },
    {
      connection,
      concurrency:
        Number(process.env.INGESTION_WORKER_CONCURRENCY) ||
        DEFAULT_CONCURRENCY,
    }
  );

  worker.on("failed", (job, error) => {
    if (!job) {
      return;
    }

    const attempts = getAttemptCount(job.data);

    if (attempts >= MAX_ATTEMPTS) {
      failedQueue
        .add(
          "failed-log",
          {
            ...job.data,
            failedReason: error ? error.message : "unknown",
            failedAt: new Date().toISOString(),
            attempts,
          },
          {
            removeOnComplete: true,
            removeOnFail: true,
          }
        )
        .catch((queueError) => {
          console.error("Failed to enqueue DLQ job", queueError);
        });
      return;
    }

    inferenceQueue
      .add(
        "inference-log",
        {
          ...job.data,
          __attempts: attempts + 1,
        },
        {
          removeOnComplete: true,
          removeOnFail: true,
        }
      )
      .catch((queueError) => {
        console.error("Failed to requeue job", queueError);
      });
  });

  worker.on("error", (error) => {
    console.error("Worker error", error);
  });

  const shutdown = async () => {
    await worker.close();
    await inferenceQueue.close();
    await failedQueue.close();
    await mongoose.disconnect();
  };

  process.on("SIGINT", () => {
    shutdown().catch((error) => console.error("Shutdown error", error));
  });

  process.on("SIGTERM", () => {
    shutdown().catch((error) => console.error("Shutdown error", error));
  });
}

startWorker().catch((error) => {
  console.error("Failed to start ingestion worker", error);
  process.exitCode = 1;
});
