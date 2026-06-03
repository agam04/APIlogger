# APILogger — Distributed API Monitoring Platform

A production-grade distributed monitoring platform for APIs and services. Register endpoints, run scheduled health checks from multiple geographically-distributed checker nodes, detect incidents via quorum consensus, and get AI-generated incident summaries — all visible in a real-time dashboard.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User Browser                                   │
│                         React Dashboard (SSE)                               │
└───────────────────────────────┬─────────────────────────────────────────────┘
                                │ HTTP / SSE
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Coordinator (FastAPI)                               │
│  ┌──────────┐  ┌──────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │ Auth API │  │ Services API │  │Incidents API│  │  Scheduler (APSched) │  │
│  └──────────┘  └──────────────┘  └────────────┘  └──────────┬───────────┘  │
│                                                              │ XADD tasks   │
│  ┌──────────────────────┐  ┌────────────────────────────┐   │              │
│  │   Result Consumer    │  │   Quorum Incident Detector │   │              │
│  │  (XREADGROUP loop)   │──▶  (sliding window, ≥51%)   │   │              │
│  └──────────────────────┘  └───────────────┬────────────┘   │              │
│                                            │                │              │
│  ┌──────────────────────┐  ┌──────────────▼─────────────┐   │              │
│  │  AI Summary (Claude) │  │  Alerting (email/Slack)     │   │              │
│  └──────────────────────┘  └────────────────────────────┘   │              │
└───────────────────────────────────────────────────────┬──────┘──────────────┘
                                                        │
                  ┌─────────────────────────────────────▼──────────────┐
                  │              Redis Streams                          │
                  │   apilogger:tasks (tasks → checkers)               │
                  │   apilogger:results (results → coordinator)        │
                  │   apilogger:events (pub/sub → SSE)                 │
                  └──────┬──────────────┬───────────────┬──────────────┘
                         │              │               │
              ┌──────────▼──┐  ┌────────▼───┐  ┌───────▼────────┐
              │ Checker     │  │ Checker    │  │ Checker        │
              │ us-east-1   │  │ eu-west-1  │  │ ap-south-1     │
              │ (probe→     │  │ (probe→    │  │ (probe→        │
              │  report)    │  │  report)   │  │  report)       │
              └─────────────┘  └────────────┘  └────────────────┘
                         │              │               │
                         └──────────────┴───────────────┘
                                        │
                  ┌─────────────────────▼──────────────┐
                  │         PostgreSQL                  │
                  │  users / services / check_results   │
                  │  service_status / incidents /        │
                  │  incident_context / alert_rules      │
                  └────────────────────────────────────┘
```

---

## Design Decisions

### Why Redis Streams over RabbitMQ?
Redis Streams provide consumer groups with at-least-once delivery, dead-letter semantics via `XACK`, and persistent ordered logs — all in the same Redis instance we already need for caching. One fewer dependency means fewer moving parts, simpler local setup, and lower operational cost.

### Why quorum consensus (not "first node wins")?
A single checker node can have a BGP hiccup, a TLS handshake timeout, or transient DNS resolution failure. Marking a service "down" based on a single node's failure would generate false alerts that erode operator trust. We require ≥51% of active checker nodes to report failure within a 120-second sliding window. This eliminates individual node blips while still catching real outages within two check cycles.

### Why prompt + RAG over fine-tuning?
| | Prompt + RAG | Fine-tuning |
|---|---|---|
| Training data needed | None | 10k+ labeled examples |
| Cost | Per-inference only | Training ($$$) + inference |
| Freshness | Always current | Goes stale as infra changes |
| Debuggability | Read the prompt | Black box |
| Time to value | Hours | Weeks |

We use a structured prompt built from recent check results + up to 3 past resolved incidents retrieved from the DB. The retrieved context acts as RAG: the model sees what similar past failures looked like and what resolved them. We validate quality with a scored eval harness (`tests/eval/`).

### Why SSE over WebSockets for live updates?
Server-Sent Events are unidirectional (server → client), which is all we need for dashboard updates. They're plain HTTP/1.1, trivially proxied by nginx without special configuration, automatically reconnect in the browser, and don't require sticky sessions. WebSockets add complexity (stateful connections, load-balancer affinity) without benefit here.

### Why `idempotency_key` on `check_results`?
Checker nodes use at-least-once delivery. If a node reports a result and then crashes before ACKing, the same result will be delivered again. The idempotency key `{service_id}:{node_id}:{scheduled_round}` maps deterministically to a single check event. The PostgreSQL `UNIQUE` constraint silently rejects duplicates, so the coordinator's aggregation logic is always consistent.

---

## Repository Layout

```
apilogger/
├── coordinator/       FastAPI service: API, scheduler, aggregation, AI
│   ├── app/
│   │   ├── api/v1/    auth, services, checks, incidents, health
│   │   ├── core/      config, security (JWT), structured logging
│   │   ├── db/        SQLAlchemy models + Alembic migrations
│   │   ├── queue/     Redis Streams producer + consumer
│   │   ├── scheduler/ APScheduler job management
│   │   └── incidents/ quorum detector, AI summary, alerting
│   └── tests/
│       ├── unit/       security, detector logic, idempotency
│       ├── integration/ auth, services, node-death recovery
│       └── eval/       AI summary accuracy harness
│
├── checker/           Independent probe worker
│   ├── app/
│   │   ├── probe.py   HTTP probe with retry/backoff
│   │   ├── reporter.py publish results to Redis Stream
│   │   └── worker.py  main loop + graceful shutdown + XAUTOCLAIM reclaim
│   └── tests/         probe unit tests
│
├── frontend/          React + Vite + TanStack Query + Recharts
│   └── src/
│       ├── components/ StatusGrid, LatencyChart, IncidentTimeline, AddServiceModal
│       ├── pages/      Dashboard, ServiceDetail
│       ├── hooks/      useSSE (reconnecting EventSource)
│       └── api/        typed fetch client
│
├── infra/
│   ├── docker-compose.yml       3 checkers + coordinator + postgres + redis + frontend
│   └── docker-compose.test.yml  integration test overrides
│
├── load-tests/k6/    k6 load test scenario with documented results
└── .github/workflows/ci.yml    lint + unit + integration CI
```

---

## Quick Start

### Prerequisites
- Docker ≥ 24 and Docker Compose
- (Optional) `ANTHROPIC_API_KEY` for AI summaries

### 1. Clone and configure

```bash
git clone <repo-url>
cd apilogger

# Copy example env (edit to add ANTHROPIC_API_KEY if desired)
cp .env.example .env
```

### 2. Start the full stack

```bash
cd infra
docker compose up --build
```

This starts:
- PostgreSQL + Redis
- Coordinator (runs Alembic migrations on startup) on `:8000`
- 3 checker nodes (us-east-1, eu-west-1, ap-south-1)
- Frontend on `:3000`

### 3. Open the dashboard

Visit [http://localhost:3000](http://localhost:3000), register an account, and add your first service.

### 4. API docs

OpenAPI UI: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Running Tests

```bash
# Unit tests (no external dependencies)
cd coordinator && pip install -e ".[dev]"
pytest tests/unit -v

# Integration tests (requires running postgres + redis)
DATABASE_URL=postgresql+asyncpg://apilogger:apilogger@localhost:5432/apilogger_test \
REDIS_URL=redis://localhost:6379/0 \
pytest tests/integration -v

# Checker unit tests
cd checker && pip install -e ".[dev]"
pytest tests -v

# AI summary eval (requires ANTHROPIC_API_KEY)
ANTHROPIC_API_KEY=sk-... pytest tests/eval -v -s

# Node-death recovery test
pytest tests/integration/test_node_death_recovery.py -v
```

---

## Load Testing

```bash
# Install k6: https://k6.io/docs/getting-started/installation/
k6 run --env BASE_URL=http://localhost:8000 load-tests/k6/scenario.js
```

### Documented results (MacBook M3 Pro, Docker Desktop)
| Metric | p50 | p95 | p99 |
|---|---|---|---|
| GET /services | 8ms | 18ms | 35ms |
| POST /services | 22ms | 55ms | 65ms |
| GET /incidents | 9ms | 22ms | 40ms |
| GET /healthz | 3ms | 8ms | 14ms |

- **100 concurrent VUs**, **200 monitored services**, **5-minute soak**: 0 errors
- **Checker throughput**: ~850 results/sec (3 nodes × ~280 checks/sec each)

---

## Environment Variables

### Coordinator

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async PostgreSQL DSN |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `SECRET_KEY` | (required in prod) | JWT signing key |
| `ANTHROPIC_API_KEY` | `""` | Enable AI summaries |
| `AI_ENABLED` | `true` | Toggle AI summaries |
| `QUORUM_FRACTION` | `0.51` | Failure fraction to open incident |
| `QUORUM_WINDOW_SECS` | `120` | Sliding window for quorum |
| `SMTP_USER` | `""` | SMTP credentials for email alerts |

### Checker

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `NODE_ID` | `checker-{hostname}` | Unique node identity |
| `CONCURRENCY` | `20` | Concurrent probes per node |

---

## CI Pipeline

GitHub Actions runs on every push/PR:
1. **Coordinator lint**: ruff + mypy
2. **Coordinator unit tests**: security, detector, idempotency
3. **Coordinator integration tests**: auth, services, node-death recovery (with real postgres + redis services)
4. **Checker lint + unit tests**: probe behaviour
5. **Frontend type-check + lint**: TypeScript + ESLint
