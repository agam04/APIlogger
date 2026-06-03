const BASE = "/api/v1";

function getToken(): string | null {
  return localStorage.getItem("token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// ---- Auth ----
export interface TokenResponse { access_token: string; token_type: string; }
export interface UserResponse { id: string; email: string; }

export const api = {
  auth: {
    register: (email: string, password: string) =>
      request<UserResponse>("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
    login: (email: string, password: string) =>
      request<TokenResponse>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  },

  // ---- Services ----
  services: {
    list: (page = 1, pageSize = 50) =>
      request<PaginatedServices>(`/services?page=${page}&page_size=${pageSize}`),
    get: (id: string) => request<ServiceResponse>(`/services/${id}`),
    create: (body: ServiceCreate) =>
      request<ServiceResponse>("/services", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: Partial<ServiceCreate>) =>
      request<ServiceResponse>(`/services/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id: string) => request<void>(`/services/${id}`, { method: "DELETE" }),
  },

  // ---- Checks ----
  checks: {
    list: (serviceId: string, page = 1, pageSize = 100) =>
      request<PaginatedChecks>(`/services/${serviceId}/checks?page=${page}&page_size=${pageSize}`),
    stats: (serviceId: string, since?: string, until?: string) => {
      const params = new URLSearchParams();
      if (since) params.set("since", since);
      if (until) params.set("until", until);
      return request<LatencyStats>(`/services/${serviceId}/checks/stats?${params}`);
    },
  },

  // ---- Incidents ----
  incidents: {
    list: (openOnly = false, page = 1) =>
      request<PaginatedIncidents>(`/incidents?open_only=${openOnly}&page=${page}`),
    get: (id: string) => request<IncidentResponse>(`/incidents/${id}`),
    generateSummary: (id: string) =>
      request<{ status: string }>(`/incidents/${id}/generate-summary`, { method: "POST" }),
  },

  // ---- Alert rules ----
  alertRules: {
    list: (serviceId: string) =>
      request<AlertRuleResponse[]>(`/services/${serviceId}/alert-rules`),
    create: (serviceId: string, body: AlertRuleCreate) =>
      request<AlertRuleResponse>(`/services/${serviceId}/alert-rules`, {
        method: "POST", body: JSON.stringify(body),
      }),
    delete: (serviceId: string, ruleId: string) =>
      request<void>(`/services/${serviceId}/alert-rules/${ruleId}`, { method: "DELETE" }),
  },
};

// ---- Types ----
export interface ServiceStatus {
  current_status: string;
  since: string | null;
  uptime_7d: number | null;
  p50_ms: number | null;
  p99_ms: number | null;
}
export interface ServiceResponse {
  id: string; name: string; url: string; method: string;
  interval_secs: number; timeout_ms: number; expected_status: number;
  headers: Record<string, string>; body: string | null; is_active: boolean;
  created_at: string; status: ServiceStatus | null;
}
export interface ServiceCreate {
  name: string; url: string; method?: string; interval_secs?: number;
  timeout_ms?: number; expected_status?: number; headers?: Record<string, string>;
  body?: string;
}
export interface PaginatedServices {
  items: ServiceResponse[]; total: number; page: number; page_size: number;
}
export interface CheckResultResponse {
  id: string; checker_node_id: string; checked_at: string; status: string;
  status_code: number | null; response_ms: number | null; error_message: string | null;
}
export interface PaginatedChecks {
  items: CheckResultResponse[]; total: number; page: number; page_size: number;
}
export interface LatencyStats {
  p50_ms: number | null; p95_ms: number | null; p99_ms: number | null;
  uptime_pct: number | null; total_checks: number;
}
export interface IncidentResponse {
  id: string; service_id: string; service_name: string; started_at: string;
  resolved_at: string | null; trigger_reason: string; ai_summary: string | null;
  ai_generated_at: string | null; alert_sent: boolean;
}
export interface PaginatedIncidents {
  items: IncidentResponse[]; total: number; page: number; page_size: number;
}
export interface AlertRuleResponse {
  id: string; channel: string; destination: string; on_incident: boolean; on_resolve: boolean;
}
export interface AlertRuleCreate {
  channel: string; destination: string; on_incident?: boolean; on_resolve?: boolean;
}
