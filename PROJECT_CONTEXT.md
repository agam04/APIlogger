# APILogger — Project Context File

Use this file to give Claude Code full context on the project in any new session.
Paste this file at the start of a conversation and say what you need.

---

## What This Is

A **production-grade distributed API/service monitoring platform** — the equivalent of a self-hosted Datadog/PagerDuty. Users register, add services they want monitored (URLs), and the system continuously probes them from multiple geographic nodes, detects outages using quorum consensus, generates AI-powered incident summaries, and sends alerts via email or Slack.

This is a **portfolio flagship project** targeting SDE roles. The resume pitch:
> "Built a distributed API monitoring platform with quorum-based incident detection across 3 geographically distributed checker nodes, Redis Streams for at-least-once message delivery, and AI-generated incident summaries using retrieval-augmented generation (RAG)."

Interview talking point:
> "The interesting problem was false-alert elimination — a single node might have a bad network path, so I require ≥51% of nodes to agree a service is failing before opening an incident. That's the same quorum pattern Cassandra and etcd use."

---

## Tech Stack

| Layer | Technology |
|---|---|
| Coordinator API | FastAPI (Python 3.11), async SQLAlchemy + asyncpg |
| Task Queue | Redis Streams (XREADGROUP / XAUTOCLAIM) |
| Database | PostgreSQL 16 with Alembic migrations |
| Checker Nodes | Python workers (3 simulated nodes: us-east, eu-west, ap-south) |
| Real-time UI updates | Server-Sent Events (SSE) via Redis pub/sub |
| AI Summaries | Anthropic Claude (primary) → Groq llama-3.3-70b (free fallback) |
| Frontend | React + Vite + TanStack Query + Recharts |
| Auth | JWT (python-jose) + bcrypt password hashing |
| Scheduling | APScheduler (syncs services from DB every 60s) |
| Alerting | Email (aiosmtplib) + Slack webhooks |
| Infra | Docker + docker-compose (8 services) |
| Logging | structlog (structured JSON) |
| Tests | pytest-asyncio, unit + integration + AI eval harness |
| Load tests | k6 |

---

## Architecture Overview

```
Browser (React)
    |
    | HTTP + SSE
    v
[Coordinator - FastAPI :8000]
    |          |           |
    |          |           v
    |          |     [PostgreSQL :5432]
    |          |       - users
    |          |       - services
    |          |       - check_results (idempotency_key UNIQUE)
    |          |       - service_status
    |          |       - incidents
    |          |       - incident_context (RAG chunks)
    |          |       - alert_rules
    |          |
    |    [Redis :6379]
    |    Streams:
    |      apilogger:tasks   → checker nodes read from here
    |      apilogger:results ← checker nodes write here
    |    Pub/Sub:
    |      apilogger:events  → SSE pushed to browser
    |
    v
[checker-us-east] [checker-eu-west] [checker-ap-south]
    All 3 independently probe each service URL
    Write results → apilogger:results stream
```

---

## Key Design Decisions (explain these in interviews)

### 1. Quorum Consensus for Incident Detection
- **What**: An incident only opens when ≥51% of checker nodes report failure within a 120-second window
- **Why**: A single node might have a bad network path. 1-of-3 failing = false alert. 2-of-3 = real problem.
- **Where**: `coordinator/app/incidents/detector.py` → `_evaluate()`
- **Pattern**: Same as Cassandra write quorum, etcd leader election

### 2. Redis Streams with At-Least-Once Delivery
- **What**: XREADGROUP for task distribution, XAUTOCLAIM for crash recovery (reclaims messages idle >60s)
- **Why**: If a checker node dies mid-probe, the un-ACKed message stays in the Pending Entry List (PEL). XAUTOCLAIM picks it up automatically.
- **Where**: `checker/app/worker.py` → `_reclaim_pending()`, `coordinator/app/queue/consumer.py`
- **Idempotency**: `check_results.idempotency_key = {service_id}:{node_id}:{scheduled_round}` — UNIQUE constraint ensures duplicate results from retries are silently dropped

### 3. AI Summaries with RAG (not fine-tuning)
- **What**: When an incident opens, fetch last 30min of check results + 3 past resolved incidents → inject as context → call LLM
- **Why**: RAG gives the model actual error messages, latency numbers, and historical patterns specific to this service
- **Provider fallback**: Anthropic (if key set) → Groq free tier (if GROQ_API_KEY set) → disabled
- **Where**: `coordinator/app/incidents/ai_summary.py`

### 4. Per-Service Lock for Incident Detection
- **What**: `_locks: dict[str, asyncio.Lock]` — one asyncio Lock per service_id
- **Why**: Prevents a race where two concurrent check results both try to open an incident for the same service
- **Where**: `coordinator/app/incidents/detector.py` → `_get_lock()`

### 5. APScheduler with Live DB Sync
- **What**: Scheduler reloads all active services from DB every 60s and diffs vs. currently-scheduled jobs
- **Why**: Services added/deleted via API are picked up without a restart
- **Where**: `coordinator/app/scheduler/scheduler.py`

---

## File Structure

```
APIlogger/
├── coordinator/                  # FastAPI backend
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── auth.py           # register + login (JWT)
│   │   │   ├── services.py       # CRUD for monitored services
│   │   │   ├── checks.py         # check result history + latency stats (p50/p95/p99)
│   │   │   ├── incidents.py      # incident list, detail, manual AI re-trigger
│   │   │   └── health.py         # /healthz + /metrics (Prometheus-style)
│   │   ├── core/
│   │   │   ├── config.py         # pydantic-settings (env vars)
│   │   │   ├── security.py       # bcrypt hash/verify + JWT create/decode
│   │   │   └── logging.py        # structlog config
│   │   ├── db/
│   │   │   ├── models.py         # 7 SQLAlchemy ORM models
│   │   │   └── migrations/versions/0001_initial_schema.py
│   │   ├── incidents/
│   │   │   ├── detector.py       # quorum logic → open/close incidents
│   │   │   ├── ai_summary.py     # RAG prompt + Anthropic/Groq providers
│   │   │   └── alerting.py       # email + Slack alerts
│   │   ├── queue/
│   │   │   ├── consumer.py       # drains results stream → persists to DB → calls detector
│   │   │   └── producer.py       # coordinator pushes check tasks to stream
│   │   ├── scheduler/
│   │   │   └── scheduler.py      # APScheduler, 60s DB sync
│   │   └── main.py               # FastAPI factory, lifespan, SSE endpoint
│   └── tests/
│       ├── unit/                 # test_detector, test_security, test_idempotency_key
│       ├── integration/          # test_auth, test_services, test_node_death_recovery
│       └── eval/                 # test_ai_summary_accuracy (4-dimension scoring)
│
├── checker/                      # Distributed probe workers
│   └── app/
│       ├── worker.py             # XREADGROUP loop + XAUTOCLAIM recovery + SIGTERM shutdown
│       ├── probe.py              # async HTTP probe (httpx)
│       └── reporter.py           # writes result to results stream
│
├── frontend/                     # React dashboard
│   └── src/
│       ├── pages/Dashboard.tsx   # service status grid + incident timeline
│       ├── pages/ServiceDetail.tsx # latency charts (Recharts), check history
│       ├── components/
│       │   ├── StatusGrid.tsx
│       │   ├── LatencyChart.tsx
│       │   ├── IncidentTimeline.tsx
│       │   └── AddServiceModal.tsx
│       ├── hooks/useSSE.ts       # subscribes to /api/v1/events for live updates
│       └── api/client.ts         # TanStack Query API client
│
├── infra/
│   └── docker-compose.yml        # 8 services: postgres, redis, coordinator, 3 checkers, frontend
│
├── load-tests/k6/scenario.js     # k6 load test script
└── .env.example                  # template for secrets
```

---

## Data Models (PostgreSQL)

```
users           id, email, hashed_pw, created_at
services        id, user_id→users, name, url, method, interval_secs, timeout_ms,
                expected_status, headers(JSONB), body, is_active
check_results   id, service_id→services, checker_node_id, checked_at, status,
                status_code, response_ms, error_message, raw_headers(JSONB),
                idempotency_key UNIQUE
service_status  service_id PK→services, current_status, since, last_checked_at,
                uptime_7d, p50_ms, p99_ms
incidents       id, service_id→services, started_at, resolved_at, trigger_reason,
                ai_summary, ai_generated_at, alert_sent
incident_context id, incident_id→incidents, chunk_text  (RAG store)
alert_rules     id, service_id→services, channel(email|slack), destination,
                on_incident, on_resolve
```

---

## API Endpoints

```
POST /api/v1/auth/register          Create account
POST /api/v1/auth/login             Get JWT token

GET  /api/v1/services               List user's services
POST /api/v1/services               Add service to monitor
GET  /api/v1/services/{id}          Service detail + current status
PUT  /api/v1/services/{id}          Update service config
DELETE /api/v1/services/{id}        Remove service

GET  /api/v1/services/{id}/checks   Paginated check result history
GET  /api/v1/services/{id}/checks/stats  Latency p50/p95/p99 + uptime %

GET  /api/v1/incidents              Paginated incident list (open_only filter)
GET  /api/v1/incidents/{id}         Incident detail + AI summary
POST /api/v1/incidents/{id}/generate-summary  Re-trigger AI summary

GET  /api/v1/events                 SSE stream for real-time status changes
GET  /healthz                       Health check (used by docker-compose)
GET  /metrics                       Internal counters (checks_ingested, incidents_opened, etc.)
GET  /docs                          Swagger UI (auto-generated)
```

---

## Environment Variables (.env)

```bash
# Required
SECRET_KEY=change-me-in-production
DATABASE_URL=postgresql+asyncpg://apilogger:apilogger@postgres:5432/apilogger
REDIS_URL=redis://redis:6379/0

# AI (at least one for summaries)
ANTHROPIC_API_KEY=        # primary
GROQ_API_KEY=             # free fallback (llama-3.3-70b-versatile)

# Alerting (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SLACK_WEBHOOK_URL=

# Tuning
QUORUM_FRACTION=0.51      # fraction of nodes that must agree on failure
QUORUM_WINDOW_SECS=120    # time window for quorum evaluation
AI_ENABLED=true
```

---

## How to Run Locally

```bash
cd infra
cp ../.env.example ../.env   # fill in keys
docker compose up --build    # starts all 8 services

# Frontend: http://localhost:3000
# API docs: http://localhost:8000/docs
# Coordinator logs: docker compose logs -f coordinator
```

---

## What's Working (as of 2026-06-03)

- [x] Full auth (register, login, JWT)
- [x] Service CRUD
- [x] 3 checker nodes probing services every N seconds
- [x] Redis Streams task queue with at-least-once delivery
- [x] Quorum-based incident detection
- [x] AI incident summaries (Anthropic + Groq fallback)
- [x] SSE real-time dashboard updates
- [x] Latency stats (p50/p95/p99 via PostgreSQL percentile_cont)
- [x] Idempotent result ingestion
- [x] XAUTOCLAIM crash recovery
- [x] Docker-compose full stack

## Still To Do (tomorrow)

- [ ] `git init` + push to GitHub
- [ ] GitHub Actions CI (lint + tests on push)
- [ ] Deploy to Fly.io or Railway (get a live URL)
- [ ] Architecture diagram (Mermaid or Excalidraw) for README
- [ ] Write proper README with demo screenshot
- [ ] Alert rules UI (backend exists, no frontend yet)
- [ ] Remove `version: "3.9"` from docker-compose.yml (deprecated)

---

## Known Bugs Fixed During Build (good to know for interviews)

1. **hatchling can't find package** — project name `apilogger-coordinator` doesn't match dir `app/`. Fix: add `[tool.hatch.build.targets.wheel] packages = ["app"]` to pyproject.toml
2. **passlib + bcrypt>=4.0 incompatibility** — passlib is unmaintained; its internal bcrypt wrap-bug detection crashes with modern bcrypt. Fix: replaced passlib entirely with direct `import bcrypt` calls.
3. **SQLAlchemy `from sqlalchemy.func import count` fails** — `func` is not a submodule. Fix: `from sqlalchemy import func` then `func.count()`.
4. **FastAPI ResponseValidationError on UUID field** — Pydantic v2 won't auto-coerce UUID→str even with `from_attributes=True`. Fix: explicitly `str(user.id)` when constructing response models.
5. **docker-compose YAML merge bug** — YAML anchors with `<<:` inside an `environment:` block merges structural keys (build, depends_on) as env vars. Fix: separate anchor to only contain structural keys.
