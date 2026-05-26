const mongoose = require("mongoose");

const { Schema } = mongoose;

/**
 * @typedef {Object} SessionDocument
 * @property {string} sessionId - Stable session identifier.
 * @property {string} [title] - Human-friendly title.
 * @property {Date} createdAt
 * @property {Date} updatedAt
 */

const SessionSchema = new Schema(
  {
    sessionId: {
      type: String,
      required: true,
      unique: true,
      index: true,
      trim: true,
    },
    title: {
      type: String,
      default: "",
      trim: true,
    },
  },
  {
    timestamps: true,
  }
);

module.exports = mongoose.model("Session", SessionSchema);
