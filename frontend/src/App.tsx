import { useState } from "react";
import { Routes, Route, Navigate, useNavigate } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { Dashboard } from "./pages/Dashboard";
import { ServiceDetail } from "./pages/ServiceDetail";
import { api } from "./api/client";

function isAuthenticated(): boolean {
  return !!localStorage.getItem("token");
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  return isAuthenticated() ? <>{children}</> : <Navigate to="/login" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
      <Route path="/services/:id" element={<RequireAuth><ServiceDetail /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isRegister, setIsRegister] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loginMutation = useMutation({
    mutationFn: () => api.auth.login(email, password),
    onSuccess: (data) => {
      localStorage.setItem("token", data.access_token);
      navigate("/");
    },
    onError: (e: Error) => setError(e.message),
  });

  const registerMutation = useMutation({
    mutationFn: () => api.auth.register(email, password),
    onSuccess: () => loginMutation.mutate(),
    onError: (e: Error) => setError(e.message),
  });

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    isRegister ? registerMutation.mutate() : loginMutation.mutate();
  }

  const isPending = loginMutation.isPending || registerMutation.isPending;

  const inputStyle: React.CSSProperties = {
    width: "100%", padding: "10px 14px", borderRadius: "8px",
    border: "1px solid #334155", background: "#0f172a",
    color: "#e2e8f0", fontSize: "15px",
  };

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{
        background: "#1e293b", borderRadius: "14px", padding: "36px 32px",
        width: "380px", border: "1px solid #334155",
      }}>
        <h1 style={{ fontSize: "22px", fontWeight: 800, marginBottom: "4px" }}>APILogger</h1>
        <p style={{ color: "#64748b", fontSize: "13px", marginBottom: "28px" }}>Distributed API Monitoring</p>

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          <div>
            <label style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "4px" }}>Email</label>
            <input style={inputStyle} type="email" value={email} required
              onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label style={{ display: "block", fontSize: "12px", color: "#94a3b8", marginBottom: "4px" }}>Password</label>
            <input style={inputStyle} type="password" value={password} required
              onChange={(e) => setPassword(e.target.value)} />
          </div>

          {error && <div style={{ color: "#ef4444", fontSize: "13px" }}>{error}</div>}

          <button type="submit" disabled={isPending} style={{
            padding: "11px", borderRadius: "8px", border: "none",
            background: "#3b82f6", color: "white", fontWeight: 700, cursor: "pointer", fontSize: "15px",
            marginTop: "4px",
          }}>
            {isPending ? "…" : isRegister ? "Create Account" : "Sign In"}
          </button>
        </form>

        <div style={{ marginTop: "18px", textAlign: "center", fontSize: "13px", color: "#64748b" }}>
          {isRegister ? "Already have an account? " : "Don't have an account? "}
          <button
            onClick={() => { setIsRegister(!isRegister); setError(null); }}
            style={{ background: "none", border: "none", color: "#3b82f6", cursor: "pointer", fontSize: "13px" }}
          >
            {isRegister ? "Sign in" : "Register"}
          </button>
        </div>
      </div>
    </div>
  );
}
