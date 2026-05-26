import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fetchAnalytics } from "../lib/api";

const PIE_COLORS = ["#34d0c1", "#ff9f43", "#4fb3ff", "#b6f23b", "#ff6b6b"];

function DashboardView() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let ignore = false;

    const loadAnalytics = async () => {
      setLoading(true);
      setError(null);

      try {
        const payload = await fetchAnalytics();
        if (!ignore) {
          setData(payload);
        }
      } catch (loadError) {
        if (!ignore) {
          setError(loadError.message || "Failed to load analytics");
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    };

    loadAnalytics();

    return () => {
      ignore = true;
    };
  }, []);

  const latencyData = data?.latency?.series || [];
  const throughputData = data?.throughput?.series || [];
  const errorsData = data?.errors?.series || [];

  const errorRateData = useMemo(() => {
    return errorsData.map((entry) => {
      const total = entry.success + entry.error;
      const rate = total ? Math.round((entry.error / total) * 1000) / 10 : 0;
      return {
        name: entry.model,
        value: rate,
        success: entry.success,
        error: entry.error,
      };
    });
  }, [errorsData]);

  const tooltipStyle = {
    backgroundColor: "rgba(18, 26, 31, 0.9)",
    borderColor: "rgba(47, 63, 74, 0.7)",
    borderRadius: "12px",
  };

  return (
    <section className="flex flex-col gap-4">
      {error ? (
        <div className="panel px-4 py-3 text-sm text-accent">{error}</div>
      ) : null}

      <div className="panel px-4 py-4">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <div className="text-xs uppercase tracking-[0.3em] text-muted">
              Latency averages
            </div>
            <h2 className="font-display text-xl">Last 24 hours</h2>
          </div>
          <span className="text-xs text-muted">ms</span>
        </div>
        <div className="h-72">
          {loading ? (
            <div className="text-sm text-muted">Loading latency data...</div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={latencyData} margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(47,63,74,0.5)" />
                <XAxis dataKey="provider" stroke="#9fb0bf" />
                <YAxis stroke="#9fb0bf" />
                <Tooltip contentStyle={tooltipStyle} />
                <Line
                  type="monotone"
                  dataKey="avgTtfbMs"
                  name="TTFB"
                  stroke="#34d0c1"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="avgTotalMs"
                  name="Total"
                  stroke="#ff9f43"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="panel px-4 py-4">
          <div className="mb-4">
            <div className="text-xs uppercase tracking-[0.3em] text-muted">
              Token throughput
            </div>
            <h2 className="font-display text-xl">Hourly totals</h2>
          </div>
          <div className="h-72">
            {loading ? (
              <div className="text-sm text-muted">Loading throughput data...</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={throughputData} margin={{ left: 8, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(47,63,74,0.5)" />
                  <XAxis dataKey="hour" stroke="#9fb0bf" hide={false} />
                  <YAxis stroke="#9fb0bf" />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Bar dataKey="totalTokens" fill="#4fb3ff" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="panel px-4 py-4">
          <div className="mb-4">
            <div className="text-xs uppercase tracking-[0.3em] text-muted">
              Error rates
            </div>
            <h2 className="font-display text-xl">By model</h2>
          </div>
          <div className="h-72">
            {loading ? (
              <div className="text-sm text-muted">Loading error data...</div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Tooltip contentStyle={tooltipStyle} formatter={(value) => `${value}%`} />
                  <Pie
                    data={errorRateData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={50}
                    outerRadius={100}
                    paddingAngle={3}
                    label={(entry) => `${entry.name} ${entry.value}%`}
                  >
                    {errorRateData.map((entry, index) => (
                      <Cell key={`cell-${entry.name}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

export default DashboardView;
