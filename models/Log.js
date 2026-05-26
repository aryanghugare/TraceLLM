const mongoose = require("mongoose");

const { Schema } = mongoose;

/**
 * @typedef {"user" | "assistant" | "system"} LogRole
 */

/**
 * @typedef {"openai" | "gemini" | "anthropic"} Provider
 */

/**
 * @typedef {Object} LatencyMetrics
 * @property {number} [ttfbMs] - Time to first token in milliseconds.
 * @property {number} [totalMs] - Total response time in milliseconds.
 */

/**
 * @typedef {Object} TokenUsage
 * @property {number} [prompt]
 * @property {number} [completion]
 * @property {number} [total]
 */

/**
 * @typedef {"success" | "error"} ResponseStatus
 */

/**
 * @typedef {Object} AssistantMetadata
 * @property {Provider} provider
 * @property {string} model
 * @property {LatencyMetrics} [latency]
 * @property {TokenUsage} [tokenUsage]
 * @property {ResponseStatus} status
 */

/**
 * @typedef {Object} LogDocument
 * @property {string} sessionId
 * @property {LogRole} role
 * @property {string} content
 * @property {AssistantMetadata} [metadata]
 * @property {Date} createdAt
 * @property {Date} updatedAt
 */

const LatencySchema = new Schema(
  {
    ttfbMs: { type: Number, min: 0 },
    totalMs: { type: Number, min: 0 },
  },
  { _id: false }
);

const TokenUsageSchema = new Schema(
  {
    prompt: { type: Number, min: 0 },
    completion: { type: Number, min: 0 },
    total: { type: Number, min: 0 },
  },
  { _id: false }
);

const AssistantMetadataSchema = new Schema(
  {
    provider: {
      type: String,
      enum: ["openai", "gemini", "anthropic"],
      required: true,
    },
    model: {
      type: String,
      required: true,
      trim: true,
    },
    latency: {
      type: LatencySchema,
      default: undefined,
    },
    tokenUsage: {
      type: TokenUsageSchema,
      default: undefined,
    },
    status: {
      type: String,
      enum: ["success", "error"],
      required: true,
    },
  },
  { _id: false }
);

const LogSchema = new Schema(
  {
    sessionId: {
      type: String,
      required: true,
      index: true,
      trim: true,
    },
    role: {
      type: String,
      required: true,
      enum: ["user", "assistant", "system"],
      index: true,
    },
    content: {
      type: String,
      required: true,
    },
    metadata: {
      type: AssistantMetadataSchema,
      required: function requiredMetadata() {
        return this.role === "assistant";
      },
      default: undefined,
    },
  },
  {
    timestamps: true,
  }
);

module.exports = mongoose.model("Log", LogSchema);
