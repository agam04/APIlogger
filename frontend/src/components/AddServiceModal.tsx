import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ServiceCreate } from "../api/client";

interface Props {
  onClose: () => void;
}

export function AddServiceModal({ onClose }: Props) {
  const qc = useQueryClient();
  const [form, setForm] = useState<ServiceCreate>({
    name: "",
    url: "",
    method: "GET",
    interval_secs: 60,
    timeout_ms: 5000,
    expected_status: 200,
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (body: ServiceCreate) => api.services.create(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["services"] });
      onClose();
    },
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    mutation.mutate(form);
  }

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "8px 12px", borderRadius: "6px",
    border: "1px solid #334155", background: "#0f172a",
    color: "#e2e8f0", fontSize: "14px",
  };
  const labelStyle: React.CSSProperties = { display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "4px" };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
    }}>
      <div style={{
        background: "#1e293b", borderRadius: "12px", padding: "28px",
        width: "460px", maxWidth: "95vw", border: "1px solid #334155",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "20px" }}>
          <h2 style={{ fontSize: "18px", fontWeight: 700 }}>Add Service</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#64748b", fontSize: "20px", cursor: "pointer" }}>✕</button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          <div>
            <label style={labelStyle}>Name</label>
            <input style={inputStyle} value={form.name} required
              onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label style={labelStyle}>URL</label>
            <input style={inputStyle} value={form.url} type="url" required
              onChange={(e) => setForm(f => ({ ...f, url: e.target.value }))} />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px" }}>
            <div>
              <label style={labelStyle}>Method</label>
              <select style={inputStyle} value={form.method}
                onChange={(e) => setForm(f => ({ ...f, method: e.target.value }))}>
                {["GET", "POST", "HEAD", "PUT", "PATCH"].map(m => <option key={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle}>Interval (s)</label>
              <input style={inputStyle} type="number" min={10} value={form.interval_secs}
                onChange={(e) => setForm(f => ({ ...f, interval_secs: Number(e.target.value) }))} />
            </div>
            <div>
              <label style={labelStyle}>Expected status</label>
              <input style={inputStyle} type="number" value={form.expected_status}
                onChange={(e) => setForm(f => ({ ...f, expected_status: Number(e.target.value) }))} />
            </div>
          </div>

          {error && <div style={{ color: "#ef4444", fontSize: "13px" }}>{error}</div>}

          <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end", marginTop: "4px" }}>
            <button type="button" onClick={onClose} style={{
              padding: "8px 18px", borderRadius: "6px", border: "1px solid #334155",
              background: "transparent", color: "#94a3b8", cursor: "pointer",
            }}>
              Cancel
            </button>
            <button type="submit" disabled={mutation.isPending} style={{
              padding: "8px 18px", borderRadius: "6px", border: "none",
              background: "#3b82f6", color: "white", fontWeight: 600, cursor: "pointer",
            }}>
              {mutation.isPending ? "Adding..." : "Add Service"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
