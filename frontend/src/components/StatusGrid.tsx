import { ServiceResponse } from "../api/client";

const STATUS_COLORS: Record<string, string> = {
  up: "#22c55e",
  down: "#ef4444",
  degraded: "#f59e0b",
  unknown: "#6b7280",
};

const STATUS_BG: Record<string, string> = {
  up: "rgba(34,197,94,0.1)",
  down: "rgba(239,68,68,0.1)",
  degraded: "rgba(245,158,11,0.1)",
  unknown: "rgba(107,114,128,0.1)",
};

interface Props {
  services: ServiceResponse[];
  liveStatuses: Record<string, string>;
  onSelect: (id: string) => void;
}

export function StatusGrid({ services, liveStatuses, onSelect }: Props) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "16px" }}>
      {services.map((svc) => {
        const currentStatus = liveStatuses[svc.id] ?? svc.status?.current_status ?? "unknown";
        const color = STATUS_COLORS[currentStatus] ?? STATUS_COLORS.unknown;
        const bg = STATUS_BG[currentStatus] ?? STATUS_BG.unknown;
        const uptime = svc.status?.uptime_7d;
        const p50 = svc.status?.p50_ms;

        return (
          <div
            key={svc.id}
            onClick={() => onSelect(svc.id)}
            style={{
              background: bg,
              border: `1px solid ${color}`,
              borderRadius: "10px",
              padding: "16px",
              cursor: "pointer",
              transition: "transform 0.1s",
            }}
            onMouseEnter={(e) => ((e.currentTarget as HTMLDivElement).style.transform = "scale(1.01)")}
            onMouseLeave={(e) => ((e.currentTarget as HTMLDivElement).style.transform = "scale(1)")}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: "15px", marginBottom: "4px" }}>{svc.name}</div>
                <div style={{ fontSize: "11px", color: "#94a3b8", wordBreak: "break-all" }}>{svc.url}</div>
              </div>
              <StatusBadge status={currentStatus} />
            </div>
            <div style={{ marginTop: "14px", display: "flex", gap: "24px", fontSize: "12px", color: "#94a3b8" }}>
              <Metric label="7d uptime" value={uptime != null ? `${uptime}%` : "—"} />
              <Metric label="p50" value={p50 != null ? `${p50}ms` : "—"} />
              <Metric label="interval" value={`${svc.interval_secs}s`} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const color = STATUS_COLORS[status] ?? STATUS_COLORS.unknown;
  return (
    <span style={{
      fontSize: "11px", fontWeight: 600, padding: "2px 8px", borderRadius: "99px",
      border: `1px solid ${color}`, color,
      textTransform: "uppercase", letterSpacing: "0.05em",
    }}>
      {status}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ color: "#e2e8f0", fontWeight: 600, marginTop: "2px" }}>{value}</div>
    </div>
  );
}
