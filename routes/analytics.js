const express = require("express");

const Log = require("../models/Log");

const router = express.Router();

function hoursAgo(hours) {
  return new Date(Date.now() - hours * 60 * 60 * 1000);
}

function daysAgo(days) {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000);
}

router.get("/api/analytics", async (req, res, next) => {
  try {
    const last24Hours = hoursAgo(24);
    const last7Days = daysAgo(7);

    const latencyPipeline = [
      {
        $match: {
          role: "assistant",
          createdAt: { $gte: last24Hours },
          "metadata.provider": { $exists: true },
          "metadata.latency.ttfbMs": { $type: "number" },
          "metadata.latency.totalMs": { $type: "number" },
        },
      },
      {
        $group: {
          _id: "$metadata.provider",
          avgTtfbMs: { $avg: "$metadata.latency.ttfbMs" },
          avgTotalMs: { $avg: "$metadata.latency.totalMs" },
          count: { $sum: 1 },
        },
      },
      {
        $project: {
          _id: 0,
          provider: "$_id",
          avgTtfbMs: 1,
          avgTotalMs: 1,
          count: 1,
        },
      },
      { $sort: { provider: 1 } },
    ];

    const throughputPipeline = [
      {
        $match: {
          role: "assistant",
          createdAt: { $gte: last7Days },
          "metadata.tokenUsage.total": { $type: "number" },
        },
      },
      {
        $group: {
          _id: {
            $dateToString: {
              format: "%Y-%m-%dT%H:00:00.000Z",
              date: "$createdAt",
              timezone: "UTC",
            },
          },
          totalTokens: { $sum: "$metadata.tokenUsage.total" },
        },
      },
      {
        $project: {
          _id: 0,
          hour: "$_id",
          totalTokens: 1,
        },
      },
      { $sort: { hour: 1 } },
    ];

    const errorsPipeline = [
      {
        $match: {
          role: "assistant",
          "metadata.model": { $exists: true },
          "metadata.status": { $in: ["success", "error"] },
        },
      },
      {
        $group: {
          _id: "$metadata.model",
          success: {
            $sum: {
              $cond: [{ $eq: ["$metadata.status", "success"] }, 1, 0],
            },
          },
          error: {
            $sum: {
              $cond: [{ $eq: ["$metadata.status", "error"] }, 1, 0],
            },
          },
        },
      },
      {
        $project: {
          _id: 0,
          model: "$_id",
          success: 1,
          error: 1,
        },
      },
      { $sort: { model: 1 } },
    ];

    const [latency, throughput, errors] = await Promise.all([
      Log.aggregate(latencyPipeline),
      Log.aggregate(throughputPipeline),
      Log.aggregate(errorsPipeline),
    ]);

    res.json({
      latency: {
        rangeHours: 24,
        series: latency,
      },
      throughput: {
        rangeDays: 7,
        series: throughput,
      },
      errors: {
        series: errors,
      },
    });
  } catch (error) {
    next(error);
  }
});

module.exports = router;
