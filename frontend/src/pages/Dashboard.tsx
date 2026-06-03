import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { StatusGrid } from "../components/StatusGrid";
import { IncidentTimeline } from "../components/IncidentTimeline";
import { AddServiceModal } from "../components/AddServiceModal";
import { useSSE } from "../hooks/useSSE";

export function Dashboard() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [showAddModal, setShowAddModal] = useState(false);
  const [liveStatuses, setLiveStatuses] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useState<"services" | "incidents">("services");

  const { data: servicesData, isLoading: servicesLoading } = useQuery({
    queryKey: ["services"],
    queryFn: () => api.services.list(1, 100),
    refetchInterval: 30_000,
  });

  const { data: incidentsData } = useQuery({
    queryKey: ["incidents"],
    queryFn: () => api.incidents.list(false, 1),
    refetchInterval: 15_000,
  });

  useSSE((event) => {
    if (event.type === "status_change" && event.service_id && event.status) {
      setLiveStatuses((prev) => ({ ...prev, [event.service_id!]: event.status! }));
      qc.invalidateQueries({ queryKey: ["services"] });
    }
  });

  const services = servicesData?.items ?? [];
  const incidents = incidentsData?.items ?? [];
  const openIncidents = incidents.filter((i) => !i.resolved_at);

  return (
    <div style={{ maxWidth: "1200px", margin: "0 auto", padding: "24px 16px" }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "32px" }}>
        <div>
          <h1 style={{ fontSize: "24px", fontWeight: 800, letterSpacing: "-0.5px" }}>APILogger</h1>
          <div style={{ color: "#64748b", fontSize: "13px", marginTop: "2px" }}>
            {services.length} services monitored
            {openIncidents.length > 0 && (
              <span style={{ marginLeft: "12px", color: "#ef4444", fontWeight: 600 }}>
                ● {openIncidents.length} open incident{openIncidents.length > 1 ? "s" : ""}
              </span>
            )}
          </div>
        </div>
        <div style={{ display: "flex", gap: "10px" }}>
          <button
            onClick={() => setShowAddModal(true)}
            style={{
              padding: "9px 18px", borderRadius: "8px", border: "none",
              background: "#3b82f6", color: "white", fontWeight: 600, cursor: "pointer", fontSize: "14px",
            }}
          >
            + Add Service
          </button>
          <button
            onClick={() => { localStorage.removeItem("token"); navigate("/login"); }}
            style={{
              padding: "9px 18px", borderRadius: "8px", border: "1px solid #334155",
              background: "transparent", color: "#94a3b8", cursor: "pointer", fontSize: "14px",
            }}
          >
            Logout
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: "4px", marginBottom: "24px", borderBottom: "1px solid #1e293b", paddingBottom: "0" }}>
        {(["services", "incidents"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: "8px 18px", background: "none", border: "none", cursor: "pointer",
              fontWeight: 600, fontSize: "14px",
              color: activeTab === tab ? "#3b82f6" : "#64748b",
              borderBottom: activeTab === tab ? "2px solid #3b82f6" : "2px solid transparent",
              textTransform: "capitalize",
            }}
          >
            {tab}
            {tab === "incidents" && openIncidents.length > 0 && (
              <span style={{
                marginLeft: "6px", background: "#ef4444", color: "white",
                borderRadius: "99px", padding: "1px 6px", fontSize: "11px",
              }}>
                {openIncidents.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Content */}
      {activeTab === "services" && (
        servicesLoading
          ? <div style={{ color: "#64748b" }}>Loading services…</div>
          : services.length === 0
          ? <EmptyState onAdd={() => setShowAddModal(true)} />
          : <StatusGrid services={services} liveStatuses={liveStatuses} onSelect={(id) => navigate(`/services/${id}`)} />
      )}

      {activeTab === "incidents" && (
        <IncidentTimeline incidents={incidents} onSelect={(id) => navigate(`/incidents/${id}`)} />
      )}

      {showAddModal && <AddServiceModal onClose={() => setShowAddModal(false)} />}
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div style={{ textAlign: "center", padding: "80px 0", color: "#64748b" }}>
      <div style={{ fontSize: "48px", marginBottom: "16px" }}>📡</div>
      <div style={{ fontSize: "18px", fontWeight: 600, color: "#94a3b8", marginBottom: "8px" }}>No services yet</div>
      <div style={{ marginBottom: "24px" }}>Add your first API or service to start monitoring.</div>
      <button onClick={onAdd} style={{
        padding: "10px 24px", borderRadius: "8px", border: "none",
        background: "#3b82f6", color: "white", fontWeight: 600, cursor: "pointer",
      }}>
        Add Service
      </button>
    </div>
  );
}
