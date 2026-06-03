import { formatDistanceToNow, parseISO } from "date-fns";
import { IncidentResponse } from "../api/client";

interface Props {
  incidents: IncidentResponse[];
  onSelect?: (id: string) => void;
}

export function IncidentTimeline({ incidents, onSelect }: Props) {
  if (!incidents.length) {
    return <div style={{ color: "#64748b", padding: "16px 0" }}>No incidents. All systems operational.</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      {incidents.map((inc) => (
        <IncidentCard key={inc.id} incident={inc} onClick={() => onSelect?.(inc.id)} />
      ))}
    </div>
  );
}

function IncidentCard({ incident, onClick }: { incident: IncidentResponse; onClick: () => void }) {
  const isOpen = !incident.resolved_at;
  const accentColor = isOpen ? "#ef4444" : "#22c55e";

  return (
    <div
      onClick={onClick}
      style={{
        background: "#1e293b",
        border: `1px solid ${accentColor}30`,
        borderLeft: `3px solid ${accentColor}`,
        borderRadius: "8px",
        padding: "14px 16px",
        cursor: "pointer",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "6px" }}>
        <div style={{ fontWeight: 700, fontSize: "14px" }}>
          <span style={{ color: accentColor, marginRight: "8px" }}>{isOpen ? "OPEN" : "RESOLVED"}</span>
          {incident.service_name}
        </div>
        <div style={{ fontSize: "11px", color: "#64748b" }}>
          {formatDistanceToNow(parseISO(incident.started_at), { addSuffix: true })}
        </div>
      </div>

      <div style={{ fontSize: "12px", color: "#94a3b8", marginBottom: "8px" }}>
        {incident.trigger_reason}
      </div>

      {incident.ai_summary && (
        <details style={{ marginTop: "8px" }}>
          <summary style={{ fontSize: "12px", color: "#60a5fa", cursor: "pointer", userSelect: "none" }}>
            AI Analysis
          </summary>
          <pre style={{
            marginTop: "8px", fontSize: "12px", color: "#cbd5e1",
            whiteSpace: "pre-wrap", lineHeight: 1.6,
            background: "#0f172a", padding: "12px", borderRadius: "6px",
          }}>
            {incident.ai_summary}
          </pre>
        </details>
      )}

      {incident.resolved_at && (
        <div style={{ fontSize: "11px", color: "#64748b", marginTop: "6px" }}>
          Resolved {formatDistanceToNow(parseISO(incident.resolved_at), { addSuffix: true })}
        </div>
      )}
    </div>
  );
}
