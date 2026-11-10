# Maskgate

[![CI](https://github.com/yonathan001/maskgate/actions/workflows/ci.yml/badge.svg)](https://github.com/yonathan001/maskgate/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/release/python-3120/)
[![FastAPI](https://img.shields.io/badge/framework-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **A compliance-first, privacy-preserving LLM gateway.** One secure layer between your client applications and AI providers (OpenAI, Anthropic). It strips sensitive data before requests leave your boundary, restores answers seamlessly in the response, automatically fails over to backup providers, enforces per-key rate limits and spend caps, and records audit telemetry without persisting raw prompts.

```
Your App  ──>  Maskgate (Privacy, Limits, Cache)  ──>  OpenAI / Anthropic / Mock
```

---

## Key Features

- **🛡️ Zero-Leak PII Redaction & Restoration:** Automatically scans incoming prompt messages with Microsoft Presidio and custom patterns (e.g., regional phone numbers, account identifiers). Sensitive tokens are replaced in-memory with placeholders (`<PERSON_1>`, `<EMAIL_1>`) before reaching the upstream model, and restored in the final response.
- **🔄 Drop-In OpenAI Compatibility:** Implements the official OpenAI `POST /v1/chat/completions` and `GET /v1/models` specifications. Existing client applications can switch to Maskgate simply by updating their `base_url` and `api_key`.
- **⚡ Provider Fallback & Smart Retries:** Transparent failover between providers (e.g. OpenAI $\rightarrow$ Anthropic). Retries transient network issues, timeouts, `429` rate limits, and `5xx` server errors with exponential backoff and jitter, while immediately stopping on non-retryable `4xx` client errors.
- **🚦 Per-Key Rate Limiting & Spend Caps:** Protects downstream budgets with Redis-backed token bucket limits (requests per minute) and monthly spend ceilings tracked in PostgreSQL.
- **💾 Exact-Match Response Caching:** Deterministic responses (with `temperature=0`) are securely cached, skipping redundant LLM inference costs and latency.
- **📊 Privacy-Preserving Observability:** OpenTelemetry distributed tracing and structured audit logging without ever recording or leaking raw prompt and response payloads by default.

---

## Request Pipeline

Every completion request flows through a 7-step pipeline designed for security and speed:

```
Client
  | Authorization: Bearer <gateway key>
  v
1. Auth ──> 2. Limits ──> 3. Redact ──> 4. Cache Lookup ──(hit)──────────────┐
                                            | miss                           |
                                            v                                |
                            5. Provider Call: Timeout, Retry, Fallback       |
                                            |                                |
                                            v                                |
                            6. Restore Placeholders ──> 7. Record Telemetry <┘
                                            |
                                            v
                                     Client Response
```

1. **Auth:** Constant-time validation against SHA-256 hashed API keys.
2. **Limits:** Redis-backed rate limiting and monthly budget checks (`429` / `402`).
3. **Redact:** Detects private values in prompt text, mapping them to temporary in-memory placeholders.
4. **Cache:** Checks Redis cache using a canonical JSON hash of the sanitized request parameters.
5. **Provider:** Dispatches to the primary upstream provider with timeouts, retries, and automatic route failover.
6. **Restore:** Swaps placeholders back to original values in the output text (supports streaming chunk buffering).
7. **Record:** Persists sanitized request metadata, token counts, and latency metrics without storing raw prompt text.

---

## Quick Start

Maskgate is fully runnable locally in **mock mode** without requiring any live OpenAI or Anthropic API keys.

### 1. Clone & Start Containers

```bash
git clone https://github.com/yonathan001/maskgate.git
cd maskgate
cp .env.example .env
docker compose up --build -d
```

### 2. Generate a Gateway API Key

Create an API key via the Admin API using the configured `ADMIN_TOKEN`:

```bash
curl -s -X POST http://localhost:8000/admin/keys \
  -H "X-Admin-Token: change-me" \
  -H "Content-Type: application/json" \
  -d '{"name": "demo-key", "monthly_budget_usd": 25.0, "rate_limit_per_min": 60}'
```

Save the generated key returned in the response (e.g. `mg_live_...`):

```bash
export MASKGATE_KEY="mg_live_..."
```

### 3. Send a Chat Completion Request

```bash
curl -i http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $MASKGATE_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mock-fast",
    "messages": [
      {"role": "user", "content": "Hello Maskgate!"}
    ]
  }'
```

Response headers will include compliance and routing metadata:
```http
HTTP/1.1 200 OK
X-Maskgate-Provider: mock
X-Maskgate-Fallback: false
X-Maskgate-Cache: miss
X-Maskgate-PII-Count: 0
X-Request-Id: 5d630ffa-e444-4875-bcd8-7ab50d1e6e7c
```

---

## Using with the Official OpenAI Python SDK

Maskgate works with the official OpenAI Python library without any custom SDK:

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="mg_live_...",
)

response = client.chat.completions.create(
    model="mock-fast",
    messages=[
        {"role": "user", "content": "Hello from the OpenAI Python client!"}
    ],
)

print(response.choices[0].message.content)
```

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| **Language** | Python 3.12 |
| **Framework** | FastAPI (async) + Uvicorn |
| **HTTP Client** | HTTPX (async connection pooling) |
| **Database** | PostgreSQL 16 via SQLAlchemy 2 (asyncio) + asyncpg, migrations via Alembic |
| **Cache & Limits** | Redis 7 |
| **PII Detection** | Microsoft Presidio (Analyzer + Anonymizer) + Custom Regex Recognizers |
| **Configuration** | Pydantic Settings |
| **Observability** | OpenTelemetry SDK, Structured JSON logging |
| **Testing** | Pytest, Pytest-Asyncio, RESPX |

---

## Configuration

Maskgate is configured via environment variables. See [.env.example](.env.example) for defaults:

| Variable | Description | Default |
| --- | --- | --- |
| `APP_ENV` | Environment (`dev`, `test`, `prod`) | `dev` |
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `ADMIN_TOKEN` | Secret token protecting `/admin/*` routes | `change-me` |
| `OPENAI_API_KEY` | Upstream OpenAI key (optional for mock mode) | `None` |
| `ANTHROPIC_API_KEY` | Upstream Anthropic key (optional for mock mode) | `None` |
| `LOG_RAW_PAYLOADS` | Explicit opt-in to log unredacted prompts | `false` |
| `REQUEST_TIMEOUT_SECONDS` | Maximum request duration | `60` |
| `PROVIDER_ATTEMPT_TIMEOUT_SECONDS` | Per-provider attempt timeout | `20` |
| `MAX_RETRIES` | Max retries per provider route | `2` |

---

## Development & Testing

A standard [Makefile](Makefile) is provided for local development:

```bash
# Start background services (Postgres, Redis, Mock Provider)
make up

# Run full quality check (linting, typechecking, tests)
make check

# Run individual checks
make lint       # Ruff lint & format check
make typecheck  # Mypy strict type checking on app/
make test       # Pytest test suite

# Database migrations
make migrate
```

---

## Documentation

- [docs/PLAN.md](docs/PLAN.md) — Comprehensive build plan, phase acceptance criteria, and agent instructions.
- [docs/PROGRESS.md](docs/PROGRESS.md) — Phase status, implementation milestones, and design decisions.
- [docs/BACKLOG.md](docs/BACKLOG.md) — Future scope, ideas, and post-v1 backlog.

---

## License

This project is licensed under the [MIT License](LICENSE).
