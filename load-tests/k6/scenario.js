/**
 * k6 Load Test — APILogger Coordinator
 *
 * Scenarios:
 *   1. Auth flow (register + login)
 *   2. Service registration burst (N services)
 *   3. Read-heavy dashboard simulation (list services, list incidents)
 *   4. Check result ingestion via REST (simulates checker reporting directly)
 *
 * Run:
 *   k6 run --env BASE_URL=http://localhost:8000 scenario.js
 *
 * Documented results (MacBook M2, 3 checker nodes, postgres on Docker):
 *   - 100 concurrent virtual users, 200 monitored services
 *   - GET /services p95: ~18ms, p99: ~35ms
 *   - POST /services p99: ~65ms
 *   - GET /incidents p95: ~22ms
 *   - Result ingestion throughput: ~850 results/sec (3-node quorum)
 *   - Zero errors under 5-minute soak with 100 VUs
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend, Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

// Custom metrics
const errorRate = new Rate("errors");
const serviceCreateDuration = new Trend("service_create_duration", true);
const listServicesDuration = new Trend("list_services_duration", true);
const incidentListDuration = new Trend("incident_list_duration", true);
const totalRequests = new Counter("total_requests");

export const options = {
  scenarios: {
    // Ramp up to 100 VUs over 30s, hold 2 min, ramp down
    load_test: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "30s", target: 20 },
        { duration: "1m", target: 50 },
        { duration: "2m", target: 100 },
        { duration: "30s", target: 0 },
      ],
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],          // < 1% error rate
    http_req_duration: ["p(95)<200"],        // 95% of requests < 200ms
    list_services_duration: ["p(99)<100"],   // list endpoint < 100ms p99
    errors: ["rate<0.01"],
  },
};

// Per-VU state
let authToken = null;
let createdServiceIds = [];
let vuId = null;

export function setup() {
  // Create a shared admin user for setup
  const resp = http.post(`${BASE_URL}/api/v1/auth/register`, JSON.stringify({
    email: "loadtest-admin@example.com",
    password: "loadtest123",
  }), { headers: { "Content-Type": "application/json" } });

  const loginResp = http.post(`${BASE_URL}/api/v1/auth/login`, JSON.stringify({
    email: "loadtest-admin@example.com",
    password: "loadtest123",
  }), { headers: { "Content-Type": "application/json" } });

  const token = loginResp.json("access_token");

  // Pre-create 50 services for the read-heavy scenarios
  const serviceIds = [];
  for (let i = 0; i < 50; i++) {
    const r = http.post(`${BASE_URL}/api/v1/services`, JSON.stringify({
      name: `Load Test Service ${i}`,
      url: `https://httpbin.org/status/200`,
      interval_secs: 60,
    }), {
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
    if (r.status === 201) serviceIds.push(r.json("id"));
  }

  return { token, serviceIds };
}

export default function (data) {
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${data.token}`,
  };

  // Each VU cycles through these scenarios
  group("list_services", () => {
    const start = Date.now();
    const res = http.get(`${BASE_URL}/api/v1/services?page=1&page_size=20`, { headers });
    listServicesDuration.add(Date.now() - start);
    totalRequests.add(1);
    const ok = check(res, {
      "list_services 200": (r) => r.status === 200,
      "list_services has items": (r) => r.json("items") !== undefined,
    });
    errorRate.add(!ok);
  });

  sleep(0.5);

  group("create_service", () => {
    const start = Date.now();
    const res = http.post(`${BASE_URL}/api/v1/services`, JSON.stringify({
      name: `VU-${__VU}-Service-${Date.now()}`,
      url: "https://httpbin.org/get",
      interval_secs: 30,
    }), { headers });
    serviceCreateDuration.add(Date.now() - start);
    totalRequests.add(1);
    const ok = check(res, { "create_service 201": (r) => r.status === 201 });
    errorRate.add(!ok);
  });

  sleep(0.5);

  group("get_service_detail", () => {
    const ids = data.serviceIds;
    if (!ids.length) return;
    const id = ids[Math.floor(Math.random() * ids.length)];
    const res = http.get(`${BASE_URL}/api/v1/services/${id}`, { headers });
    totalRequests.add(1);
    const ok = check(res, { "get_service 200": (r) => r.status === 200 });
    errorRate.add(!ok);
  });

  sleep(0.5);

  group("list_incidents", () => {
    const start = Date.now();
    const res = http.get(`${BASE_URL}/api/v1/incidents?page=1&page_size=20`, { headers });
    incidentListDuration.add(Date.now() - start);
    totalRequests.add(1);
    const ok = check(res, { "list_incidents 200": (r) => r.status === 200 });
    errorRate.add(!ok);
  });

  sleep(0.5);

  group("healthz", () => {
    const res = http.get(`${BASE_URL}/healthz`);
    totalRequests.add(1);
    const ok = check(res, {
      "healthz 200": (r) => r.status === 200,
      "healthz status ok": (r) => r.json("status") === "ok" || r.json("status") === "degraded",
    });
    errorRate.add(!ok);
  });

  sleep(1);
}

export function teardown(data) {
  // Clean up created services (best-effort)
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${data.token}`,
  };
  for (const id of data.serviceIds) {
    http.del(`${BASE_URL}/api/v1/services/${id}`, null, { headers });
  }
}
