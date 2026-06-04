import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { subHours } from "date-fns";
import { api, AlertRuleCreate } from "../api/client";
import { LatencyChart } from "../components/LatencyChart";
import { IncidentTimeline } from "../components/IncidentTimeline";

export function ServiceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: service } = useQuery({
    queryKey: ["service", id],
    queryFn: () => api.services.get(id!),
    enabled: !!id,
  });

  const { data: checksData } = useQuery({
    queryKey: ["checks", id],
    queryFn: () => api.checks.list(id!, 1, 500),
    enabled: !!id,
    refetchInterval: 15_000,
  });

  const since = subHours(new Date(), 24).toISOString();
  const { data: stats } = useQuery({
    queryKey: ["check-stats", id],
    queryFn: () => api.checks.stats(id!, since),
    enabled: !!id,
    refetchInterval: 30_000,
  });

  const { data: incidentsData } = useQuery({
    queryKey: ["incidents", id],
    queryFn: () => api.incidents.list(false, 1),
    enabled: !!id,
  });

  const { data: alertRules = [] } = useQuery({
    queryKey: ["alert-rules", id],
    queryFn: () => api.alertRules.list(id!),
    enabled: !!id,
  });

  const deleteService = useMutation({
    mutationFn: () => api.services.delete(id!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["services"] }); navigate("/"); },
  });

  const deleteRule = useMutation({
    mutationFn: (ruleId: string) => api.alertRules.delete(id!, ruleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules", id] }),
  });

  const checks = checksData?.items ?? [];
  const incidents = (incidentsData?.items ?? []).filter((i) => i.service_id === id);

  const currentStatus = service?.status?.current_status ?? "unknown";
  const statusColor = { up: "#22c55e", down: "#ef4444", unknown: "#6b7280" }[currentStatus] ?? "#6b7280";

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto", padding: "24px 16px" }}>
      <button
        onClick={() => navigate("/")}
        style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: "14px", marginBottom: "20px" }}
      >
        ← Back to Dashboard
      </button>

      {service && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "28px" }}>
            <div>
              <h1 style={{ fontSize: "22px", fontWeight: 800 }}>{service.name}</h1>
              <div style={{ color: "#64748b", fontSize: "13px", marginTop: "2px" }}>{service.url}</div>
            </div>
            <span style={{
              fontSize: "13px", fontWeight: 700, padding: "4px 14px", borderRadius: "99px",
              border: `1px solid ${statusColor}`, color: statusColor, textTransform: "uppercase",
            }}>
              {currentStatus}
            </span>
          </div>

          {/* Stats row */}
          {stats && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "12px", marginBottom: "28px" }}>
              {[
                { label: "Uptime", value: stats.uptime_pct != null ? `${stats.uptime_pct}%` : "—" },
                { label: "p50 latency", value: stats.p50_ms != null ? `${Math.round(stats.p50_ms)}ms` : "—" },
                { label: "p95 latency", value: stats.p95_ms != null ? `${Math.round(stats.p95_ms)}ms` : "—" },
                { label: "p99 latency", value: stats.p99_ms != null ? `${Math.round(stats.p99_ms)}ms` : "—" },
                { label: "Total checks", value: stats.total_checks.toLocaleString() },
              ].map(({ label, value }) => (
                <div key={label} style={{
                  background: "#1e293b", borderRadius: "8px", padding: "14px 16px",
                  border: "1px solid #334155",
                }}>
                  <div style={{ fontSize: "11px", color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
                  <div style={{ fontSize: "20px", fontWeight: 700, marginTop: "4px" }}>{value}</div>
                </div>
              ))}
            </div>
          )}

          {/* Latency chart */}
          <Section title="Latency (last 500 checks)">
            {checks.length > 0
              ? <LatencyChart checks={checks} height={260} />
              : <div style={{ color: "#64748b", padding: "20px 0" }}>No check data yet.</div>}
          </Section>

          {/* Incidents */}
          <Section title="Incidents">
            <IncidentTimeline incidents={incidents} />
          </Section>

          {/* Recent checks table */}
          <Section title="Recent checks">
            <ChecksTable checks={checks.slice(0, 50)} />
          </Section>

          {/* Alert rules */}
          <Section title="Alert Rules">
            <AlertRulesPanel
              serviceId={id!}
              rules={alertRules}
              onDelete={(ruleId) => deleteRule.mutate(ruleId)}
              onAdded={() => qc.invalidateQueries({ queryKey: ["alert-rules", id] })}
            />
          </Section>

          {/* Danger zone */}
          <div style={{ marginTop: "40px", paddingTop: "24px", borderTop: "1px solid #1e293b" }}>
            <button
              onClick={() => { if (confirm("Delete this service and all its data?")) deleteService.mutate(); }}
              style={{
                padding: "8px 18px", borderRadius: "8px", border: "1px solid #ef4444",
                background: "transparent", color: "#ef4444", cursor: "pointer", fontSize: "13px", fontWeight: 600,
              }}
            >
              Delete Service
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function AlertRulesPanel({
  serviceId, rules, onDelete, onAdded,
}: {
  serviceId: string;
  rules: { id: string; channel: string; destination: string }[];
  onDelete: (id: string) => void;
  onAdded: () => void;
}) {
  const [channel, setChannel] = useState<"email" | "slack">("email");
  const [destination, setDestination] = useState("");
  const [saving, setSaving] = useState(false);

  const handleAdd = async () => {
    if (!destination.trim()) return;
    setSaving(true);
    const body: AlertRuleCreate = { channel, destination: destination.trim() };
    await api.alertRules.create(serviceId, body);
    setDestination("");
    setSaving(false);
    onAdded();
  };

  return (
    <div>
      {rules.length === 0 && (
        <div style={{ color: "#64748b", fontSize: "13px", marginBottom: "16px" }}>No alert rules yet.</div>
      )}
      {rules.map((r) => (
        <div key={r.id} style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "10px 14px", background: "#1e293b", borderRadius: "8px",
          marginBottom: "8px", fontSize: "13px",
        }}>
          <div>
            <span style={{ color: "#60a5fa", fontWeight: 600, marginRight: "10px", textTransform: "uppercase", fontSize: "11px" }}>{r.channel}</span>
            <span style={{ color: "#cbd5e1" }}>{r.destination}</span>
          </div>
          <button
            onClick={() => onDelete(r.id)}
            style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", fontSize: "18px", lineHeight: 1 }}
          >
            ×
          </button>
        </div>
      ))}

      <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
        <select
          value={channel}
          onChange={(e) => setChannel(e.target.value as "email" | "slack")}
          style={{ padding: "8px 10px", borderRadius: "6px", border: "1px solid #334155", background: "#1e293b", color: "#e2e8f0", fontSize: "13px" }}
        >
          <option value="email">Email</option>
          <option value="slack">Slack</option>
        </select>
        <input
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          placeholder={channel === "email" ? "you@example.com" : "https://hooks.slack.com/..."}
          style={{
            flex: 1, padding: "8px 12px", borderRadius: "6px", border: "1px solid #334155",
            background: "#1e293b", color: "#e2e8f0", fontSize: "13px",
          }}
        />
        <button
          onClick={handleAdd}
          disabled={saving || !destination.trim()}
          style={{
            padding: "8px 16px", borderRadius: "6px", border: "none",
            background: saving ? "#334155" : "#3b82f6", color: "white",
            cursor: saving ? "not-allowed" : "pointer", fontSize: "13px", fontWeight: 600,
          }}
        >
          {saving ? "Adding…" : "Add"}
        </button>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "32px" }}>
      <h2 style={{ fontSize: "15px", fontWeight: 700, color: "#94a3b8", marginBottom: "14px", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {title}
      </h2>
      {children}
    </div>
  );
}

function ChecksTable({ checks }: { checks: ReturnType<typeof Array.prototype.slice> }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
        <thead>
          <tr style={{ borderBottom: "1px solid #1e293b" }}>
            {["Time", "Node", "Status", "HTTP", "Latency", "Error"].map((h) => (
              <th key={h} style={{ textAlign: "left", padding: "8px 12px", color: "#64748b", fontWeight: 600 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {checks.map((c: any) => (
            <tr key={c.id} style={{ borderBottom: "1px solid #0f172a" }}>
              <td style={{ padding: "7px 12px", color: "#94a3b8" }}>{new Date(c.checked_at).toLocaleTimeString()}</td>
              <td style={{ padding: "7px 12px", color: "#94a3b8", fontFamily: "monospace" }}>{c.checker_node_id}</td>
              <td style={{ padding: "7px 12px" }}>
                <span style={{
                  color: c.status === "up" ? "#22c55e" : c.status === "timeout" ? "#f59e0b" : "#ef4444",
                  fontWeight: 600, textTransform: "uppercase", fontSize: "11px",
                }}>
                  {c.status}
                </span>
              </td>
              <td style={{ padding: "7px 12px", color: "#94a3b8" }}>{c.status_code ?? "—"}</td>
              <td style={{ padding: "7px 12px", color: "#94a3b8" }}>{c.response_ms != null ? `${c.response_ms}ms` : "—"}</td>
              <td style={{ padding: "7px 12px", color: "#ef4444", maxWidth: "300px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {c.error_message ?? ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
