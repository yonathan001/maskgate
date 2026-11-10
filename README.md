# Maskgate

**A compliance-first LLM gateway.** One server between your apps and AI providers (OpenAI, Anthropic). It hides private data before a request leaves, falls back to a second provider when the first fails, caches answers, enforces per-key rate limits and spend caps, and records every request without storing raw prompts.

```
Your app  ->  Maskgate  ->  OpenAI / Anthropic
```

> **Status:** planning. This README is both the project overview and the build plan for the coding agent.
> **License:** MIT.

---

## 0. Instructions for the coding agent (read first)

You are implementing this project for a developer who will show it in job interviews. Quality, tests and honesty matter more than feature count.

**Working protocol**

1. Work **one phase at a time** (section 9). Do not start a phase until the previous phase's acceptance criteria pass.
2. Before coding a phase, restate its goal and list the files you will create or change.
3. Write tests **with** the code, not after. For redaction (Phase 5), write the tests first.
4. After each phase: run `make check` (lint, types, tests), fix failures, then update `docs/PROGRESS.md` with what was done, what was decided and what is still open.
5. Commit small and often using Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). One logical change per commit.
6. If a requirement is ambiguous or a decision would change the architecture, **stop and ask** instead of guessing. Section 14 lists decisions already made.
7. Do not add features outside section 2 ("In scope"). Put ideas in `docs/BACKLOG.md`.

**Hard rules**

- **Never commit secrets.** No API keys, tokens or passwords in code, tests, fixtures, logs or docs. Use environment variables. Provide `.env.example` with fake values only.
- **Never log raw prompts or responses by default.** Only redacted text may be stored or traced. Raw logging is an explicit opt-in setting (`LOG_RAW_PAYLOADS=true`) and defaults to `false`.
- **Never send unredacted private data to a provider** when redaction is enabled for the key.
- **Tests must not call real providers.** Use the mock provider. A single optional smoke test may call real providers only when `RUN_LIVE_TESTS=1` and keys are set.
- Do not invent benchmark numbers. Only report numbers that were measured and saved under `load-test/results/`.
- Do not claim the project is better than LiteLLM or other gateways. Document limits honestly.

---

## 1. Goals and non-goals

**Goals**

- A working OpenAI-compatible gateway that an existing OpenAI client can use by changing only its base URL.
- Provider fallback, exact-match caching, streaming, per-key limits and budgets.
- Privacy as the centerpiece: PII redaction before the provider call, restoration in the response, and tests proving that private values never reach the provider, the logs or the traces.
- Fully runnable locally with `docker compose up` and **no real provider keys** (mock mode).
- A clear, honest README, architecture doc and published load-test results.

**Non-goals (v1)**

- More than two real providers, smart model routing, billing, multi-region, semantic cache, user management UI, fine-tuning support.
- Replacing LiteLLM or similar tools. This is a focused, well-tested project.

---

## 2. Scope

**In scope (v1)**

- `POST /v1/chat/completions` (OpenAI-compatible, streaming and non-streaming)
- `GET /v1/models`
- Providers: OpenAI and Anthropic, plus a built-in mock provider
- Gateway API keys (hashed), per-key rate limit and monthly budget
- PII redaction and restoration
- Exact-match response cache (non-streaming only)
- Retries, timeouts, fallback
- Request log, audit log, cost tracking
- Admin API and a small Next.js dashboard
- OpenTelemetry traces and metrics
- Docker, CI, load tests

**Out of scope (v1)**: see non-goals. Record new ideas in `docs/BACKLOG.md`.

---

## 3. Tech stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.12 |
| Web framework | FastAPI (async) |
| HTTP client | httpx (async) |
| Database | PostgreSQL 16 via SQLAlchemy 2 (async) + asyncpg, migrations with Alembic |
| Cache / limits | Redis 7 |
| PII detection | Microsoft Presidio (analyzer + anonymizer) plus custom recognizers |
| Settings | pydantic-settings |
| Dashboard | Next.js (App Router) + TypeScript |
| Observability | OpenTelemetry (traces + metrics), structured JSON logs |
| Testing | pytest, pytest-asyncio, respx (HTTP mocking), testcontainers or docker compose services |
| Load testing | k6 |
| Quality | ruff (lint + format), mypy (strict on `app/`), gitleaks |
| CI | GitHub Actions |
| Containers | Docker, docker compose |

If a choice must change, record it in `docs/ADR/` with the reason.

---

## 4. Repository layout

```
maskgate/
├── README.md
├── LICENSE                      # MIT
├── Makefile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── .github/workflows/ci.yml
├── gateway/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── migrations/
│   ├── app/
│   │   ├── main.py              # FastAPI app factory, routers, lifespan
│   │   ├── config.py            # pydantic-settings
│   │   ├── api/
│   │   │   ├── v1.py            # /v1/chat/completions, /v1/models
│   │   │   ├── admin.py         # /admin/*
│   │   │   └── health.py        # /health
│   │   ├── core/
│   │   │   ├── pipeline.py      # orchestrates steps 1-7
│   │   │   ├── auth.py          # key lookup + hashing
│   │   │   ├── limits.py        # rate limit + budget checks
│   │   │   ├── cache.py         # key building, get/set
│   │   │   ├── cost.py          # token counts -> cost
│   │   │   └── errors.py        # OpenAI-style error responses
│   │   ├── providers/
│   │   │   ├── base.py          # Provider protocol
│   │   │   ├── openai.py
│   │   │   ├── anthropic.py
│   │   │   ├── mock.py
│   │   │   └── registry.py      # model -> provider order (from models.yaml)
│   │   ├── redaction/
│   │   │   ├── engine.py        # detect + replace + restore
│   │   │   ├── recognizers.py   # custom patterns (e.g. +251 phones)
│   │   │   └── stream.py        # placeholder-safe stream restorer
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   └── session.py
│   │   └── telemetry/
│   │       └── otel.py
│   ├── models.yaml              # model aliases, prices, provider order
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── failure/
│       └── privacy/
├── dashboard/                   # Next.js app
├── load-test/
│   ├── k6/
│   └── results/
├── infra/
└── docs/
    ├── ARCHITECTURE.md
    ├── SECURITY.md
    ├── FAILURE-MODES.md
    ├── PROGRESS.md
    ├── BACKLOG.md
    └── ADR/
```

---

## 5. Architecture

### Request pipeline (order matters)

```
Client
  | Authorization: Bearer <gateway key>
  v
1 Auth ──> 2 Limits ──> 3 Redact ──> 4 Cache lookup ──(hit)──────────────┐
                                          | miss                          |
                                          v                               |
                          5 Provider call: timeout, retry, fallback       |
                                          |                               |
                                          v                               |
                          6 Restore placeholders ──> 7 Record <───────────┘
                                          |
                                          v
                                       Response
```

1. **Auth:** hash the bearer key (SHA-256), look it up, reject if missing or inactive (`401`).
2. **Limits:** Redis rate limit (requests per minute) and monthly budget check. Over limit returns `429` with `Retry-After`.
3. **Redact:** detect private values in every message `content` string, replace them with placeholders (`<PERSON_1>`, `<EMAIL_1>`, `<PHONE_1>` ...), and keep a per-request map in memory only. The map is never persisted or logged.
4. **Cache:** non-streaming only. Key = SHA-256 of canonical JSON of `{model, redacted messages, temperature, top_p, max_tokens, stop, tools}`. Skip the cache when `temperature > 0` unless `cache_ttl_override` is set on the key. Hit returns the stored (redacted) response, which is then restored in step 6.
5. **Provider call:** per-attempt timeout, up to 2 retries with exponential backoff + jitter on connection errors, timeouts, `429` and `5xx`. Never retry other `4xx`. After retries are exhausted, fall back to the next provider in the model's order.
6. **Restore:** replace placeholders in the response with the original values from the per-request map. For streams, use the stream restorer (section 7).
7. **Record:** write a `requests` row (redacted metadata only), update cost and budget counters, emit metrics and a trace.

### Provider interface

```python
class Provider(Protocol):
    name: str
    async def chat(self, req: ChatRequest) -> ChatResponse: ...
    def chat_stream(self, req: ChatRequest) -> AsyncIterator[ChatChunk]: ...
```

Each adapter translates the OpenAI-shaped request into the provider's format and back, and returns token usage when available. Normalize errors into `ProviderError(kind, retryable, status)` where `kind` is one of `timeout`, `rate_limit`, `server`, `client`, `network`.

### Model routing

`gateway/models.yaml` maps a public model name to an ordered provider list and prices:

```yaml
models:
  - name: gpt-4o-mini
    providers:
      - { provider: openai, upstream_model: gpt-4o-mini }
      - { provider: anthropic, upstream_model: claude-3-5-haiku-latest }
    price_per_1k: { input: 0.00015, output: 0.0006 }
  - name: mock-fast
    providers:
      - { provider: mock, upstream_model: mock-fast }
    price_per_1k: { input: 0.0, output: 0.0 }
```

Prices and upstream model names are examples. Verify current values against provider docs before publishing numbers, and keep them in this file, not in code.

---

## 6. Data model (PostgreSQL)

```sql
CREATE TABLE api_keys (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name               TEXT NOT NULL,
  key_prefix         TEXT NOT NULL,          -- first 8 chars, shown in dashboard
  key_hash           TEXT NOT NULL UNIQUE,   -- SHA-256 of the full key
  monthly_budget_usd NUMERIC(12,4) NOT NULL DEFAULT 10,
  rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
  redaction_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
  active             BOOLEAN NOT NULL DEFAULT TRUE,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE requests (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_id          UUID NOT NULL REFERENCES api_keys(id),
  model           TEXT NOT NULL,
  provider_used   TEXT,
  fallback_used   BOOLEAN NOT NULL DEFAULT FALSE,
  cache_hit       BOOLEAN NOT NULL DEFAULT FALSE,
  streamed        BOOLEAN NOT NULL DEFAULT FALSE,
  status_code     INTEGER NOT NULL,
  error_kind      TEXT,
  latency_ms      INTEGER NOT NULL,
  gateway_overhead_ms INTEGER,               -- time spent in Maskgate, not the provider
  input_tokens    INTEGER,
  output_tokens   INTEGER,
  cost_usd        NUMERIC(12,6),
  pii_count       INTEGER NOT NULL DEFAULT 0,
  pii_types       TEXT[] NOT NULL DEFAULT '{}',  -- e.g. {PERSON,EMAIL}; never the values
  trace_id        TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX requests_key_created ON requests (key_id, created_at DESC);

CREATE TABLE audit_log (
  id         BIGSERIAL PRIMARY KEY,
  actor      TEXT NOT NULL,
  action     TEXT NOT NULL,       -- key.created, key.disabled, budget.changed ...
  entity     TEXT NOT NULL,
  before     JSONB,
  after      JSONB,
  at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE provider_health (
  provider    TEXT PRIMARY KEY,
  status      TEXT NOT NULL,      -- ok | degraded | down
  last_error  TEXT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Rules:

- Store only the **hash** of each gateway key. Show the full key once, at creation.
- `requests` never contains prompt or response text.
- Monthly spend per key is `SUM(cost_usd)` for the current calendar month (UTC). Mirror it in a Redis counter for fast checks and reconcile from Postgres on startup.

---

## 7. Redaction design

**Detection**

- Use Presidio with entity types: `PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `IBAN_CODE`, `IP_ADDRESS`, `URL` (optional), `LOCATION` (optional, off by default).
- Add custom recognizers in `recognizers.py`:
  - Ethiopian phone numbers (`+251 9XXXXXXXX`, `09XXXXXXXX`, `07XXXXXXXX`, with common spacing and dash variants)
  - Generic national-ID-like and account-number-like patterns, configurable by regex in settings
- Be honest about limits: name detection is probabilistic. Document what is and is not caught in `docs/SECURITY.md`.

**Replacement**

- Placeholder format: `<TYPE_N>` where `N` increments per type within a request. The same original value always maps to the same placeholder within one request.
- The map lives only in memory for the lifetime of the request.

**Restoration (non-streaming)**

- Replace each placeholder in the response text with its original value. If the model altered a placeholder (for example changed case or spacing), leave it unchanged and increment a `restore_miss` metric.

**Restoration (streaming)** (`redaction/stream.py`)

- Provider chunks can split a placeholder (`<PER` + `SON_1>`). Keep a small buffer: when a chunk ends with a possible partial placeholder (a `<` without a closing `>` within the last ~20 characters), hold that tail until the next chunk or the end of the stream.
- On stream end, flush the buffer as-is.
- Must be covered by property-style tests that split text at every possible position.

**Never** put original values in logs, traces, metrics labels, error messages or exceptions. Wrap redaction calls so that exceptions are re-raised without the offending text.

---

## 8. API

OpenAI-compatible request and response shapes for `/v1/chat/completions`: support `model`, `messages`, `temperature`, `top_p`, `max_tokens`, `stop`, `stream`, `user`. Pass `tools` through unchanged when present, and do not attempt to redact tool schemas.

**Errors** use the OpenAI shape so existing clients work:

```json
{ "error": { "message": "Rate limit exceeded", "type": "rate_limit_error", "code": "rate_limit_exceeded" } }
```

| Status | When |
| --- | --- |
| 400 | Invalid body |
| 401 | Missing or invalid gateway key |
| 402 | Monthly budget exhausted |
| 404 | Unknown model |
| 429 | Rate limit exceeded (include `Retry-After`) |
| 502 | All providers failed |
| 504 | Overall request timeout |

**Response headers** (helpful for demos and tests):

- `X-Maskgate-Provider`, `X-Maskgate-Fallback` (`true` or `false`), `X-Maskgate-Cache` (`hit` or `miss`), `X-Maskgate-PII-Count`, `X-Request-Id`.

**Admin API** (protected by a separate `ADMIN_TOKEN`):

| Endpoint | Purpose |
| --- | --- |
| `POST /admin/keys` | Create a key (returns the full key once) |
| `GET /admin/keys` | List keys (prefix, limits, active) |
| `PATCH /admin/keys/{id}` | Change limits, budget, active flag (writes audit log) |
| `GET /admin/usage?days=30` | Usage and cost by key and day |
| `GET /admin/requests?limit=100` | Recent requests (metadata only) |
| `GET /admin/providers` | Provider health |
| `POST /admin/demo/provider-down` | Demo only: force a provider to fail (disabled unless `DEMO_MODE=true`) |

`GET /health` returns gateway status plus each provider's last known state.

---

## 9. Build plan (8 phases, about 1 week each)

Each phase ends with **acceptance criteria**. Do not move on until they pass.

### Phase 1: Skeleton and first request
- Repo scaffold, `Makefile`, Docker, docker compose (gateway, Postgres, Redis, mock provider), CI (lint, types, tests, gitleaks), `.env.example`, `.gitignore`.
- Config, DB models + first Alembic migration, API key creation via admin API with hashed storage.
- Mock provider and a **non-streaming** `/v1/chat/completions` that authenticates, calls the mock, and returns an OpenAI-shaped response.

**Acceptance**
- `docker compose up` starts everything on a clean machine.
- The official OpenAI Python client works against the gateway by changing only `base_url` and `api_key`.
- CI is green. No secrets in the repo.

### Phase 2: Real providers, retries, fallback
- OpenAI and Anthropic adapters with error normalization.
- Timeouts, retries with backoff and jitter, fallback to the next provider.
- Provider health tracking and `/health`.

**Acceptance**
- With provider A configured to fail (mock failure modes), requests succeed through provider B and `X-Maskgate-Fallback: true` is returned.
- 4xx client errors are not retried. 5xx, 429 and timeouts are.
- Tests cover: success, 500, timeout, 429, malformed body, all providers down (`502`).

### Phase 3: Cost, limits, budgets
- Token usage extraction, cost calculation from `models.yaml`.
- Redis rate limiting (fixed window with `INCR` + `EXPIRE` is acceptable) and monthly budget enforcement.
- `GET /admin/usage`.

**Acceptance**
- A key over its rate limit gets `429` with `Retry-After`. A key over budget gets `402`.
- Cost per request matches hand-calculated values in tests.
- Counters survive a gateway restart (reconciled from Postgres).

### Phase 4: Cache and streaming
- Exact-match cache for non-streaming requests (section 5, step 4).
- SSE streaming pass-through (`stream: true`) with correct OpenAI chunk format and `[DONE]`.
- Streaming fallback only before the first chunk is sent. After that, end the stream with an error event.

**Acceptance**
- A repeated deterministic request returns `X-Maskgate-Cache: hit` and no provider call is made.
- A streamed response arrives chunk by chunk and ends cleanly.
- A provider dropping a stream halfway produces a well-formed error event, not a hang.

### Phase 5: PII redaction (write tests first)
- Redaction engine, custom recognizers, restoration, stream restorer.
- `redaction_enabled` per key. Record `pii_count` and `pii_types` only.

**Acceptance**
- Privacy tests (section 11) pass: no raw private value appears in the provider request, the logs, the traces or the DB.
- Stream restorer passes split-at-every-position tests.
- `docs/SECURITY.md` lists exactly which entity types are covered, known gaps, and measured precision/recall on the project's own labeled test set (include the test set in the repo, using only synthetic data).

### Phase 6: Observability and dashboard
- Request log, audit log, OpenTelemetry traces (spans per pipeline step) and metrics (latency, overhead, cache hit rate, fallback rate, PII counts, restore misses).
- Next.js dashboard: usage and cost by key, recent requests (metadata), provider health, fallback and cache stats, PII counts by type.
- Demo-mode "provider down" toggle.

**Acceptance**
- Dashboard shows live numbers from a demo run.
- Traces show each pipeline step and contain no private values.

### Phase 7: Failure and load testing
- Failure suite (section 11) complete and documented in `docs/FAILURE-MODES.md`.
- k6 scripts in `load-test/k6/`. Run against the mock provider with fixed latency so that the numbers measure **gateway overhead**.
- Fix the slowest steps found. Save raw results to `load-test/results/` with the machine description and commit hash.

**Acceptance**
- Published: gateway overhead (p50, p95), requests per second, error rate, test machine specs.
- No result in the README that is not backed by a file in `load-test/results/`.

### Phase 8: Release
- Deploy a public demo (small VPS or cloud VM) with HTTPS, a sandbox key, seeded demo data, rate limits and a daily data reset. Mock mode must work with no provider keys.
- Finish README (quick start, `curl` examples, architecture diagram, benchmarks, limits), `ARCHITECTURE.md`, `SECURITY.md`, ADRs, demo GIF.
- Tag `v0.1.0`.

**Acceptance**
- A stranger can run the quick start in under 5 minutes.
- Definition of done (section 13) fully checked.

---

## 10. Configuration

`.env.example` (fake values only):

```
# Gateway
APP_ENV=dev
DATABASE_URL=postgresql+asyncpg://maskgate:maskgate@postgres:5432/maskgate
REDIS_URL=redis://redis:6379/0
ADMIN_TOKEN=change-me
DEMO_MODE=false
LOG_RAW_PAYLOADS=false

# Providers (leave empty to use mock only)
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
MOCK_PROVIDER_URL=http://mock-provider:9000

# Behavior
REQUEST_TIMEOUT_SECONDS=60
PROVIDER_ATTEMPT_TIMEOUT_SECONDS=20
MAX_RETRIES=2
MAX_PROMPT_CHARS=200000

# Observability
OTEL_EXPORTER_OTLP_ENDPOINT=
```

**Mock provider:** a tiny FastAPI app (or built-in module) that returns deterministic answers and can be told to fail on demand: `500`, `429`, timeout, slow response, malformed JSON, stream cut mid-way. Tests and the live demo both use it.

---

## 11. Testing strategy

| Layer | What to test |
| --- | --- |
| Unit | Cost math, cache key canonicalization, rate limiter, placeholder generation, recognizers (positive and negative cases), config parsing |
| Integration | Full request through the app against the mock provider, with real Postgres and Redis (compose or testcontainers) |
| Failure | Provider 500 / 429 / timeout / malformed JSON / stream dropped mid-way / all providers down / Redis down (fail open or closed, per ADR) / Postgres slow |
| Privacy | Send text full of synthetic private values. Assert none appear in: the request body received by the mock provider, application logs, OTel spans, DB rows, error responses |
| Stream | Restorer fed text split at every index, with multiple placeholders, with a placeholder at the very end |
| Load | k6 against the mock provider: overhead p50 / p95, req/s, error rate |

Rules:

- Use only **synthetic** personal data in tests and fixtures.
- Privacy tests are a release gate. If one fails, nothing ships.
- Coverage target: 85% for `app/core` and `app/redaction`. Do not chase coverage elsewhere.

---

## 12. Security checklist

- [ ] Gateway keys stored as hashes, shown once, compared in constant time
- [ ] Provider keys only in environment variables or a secrets manager
- [ ] Admin endpoints require `ADMIN_TOKEN`, are rate limited, and are disabled or restricted on the public demo
- [ ] No raw prompts or responses in logs, traces or the database by default
- [ ] Request size limit (`MAX_PROMPT_CHARS`) and overall timeout
- [ ] Demo endpoints (`/admin/demo/*`) refuse to run unless `DEMO_MODE=true`
- [ ] Dependency scanning and gitleaks in CI
- [ ] CORS locked down for admin and dashboard routes
- [ ] Error messages never echo request content
- [ ] Redis or DB outage behavior decided and documented in an ADR

---

## 13. Definition of done

- [ ] An existing OpenAI client works against Maskgate by changing only the base URL
- [ ] Fallback, retries, caching, rate limits, budgets and streaming all pass tests
- [ ] Privacy tests pass, and no private value appears in logs, traces or the database
- [ ] `docker compose up` works on a fresh machine, and mock mode needs no provider keys
- [ ] CI is green (lint, types, tests, gitleaks)
- [ ] Load-test results are saved in `load-test/results/` and quoted accurately in the README
- [ ] `ARCHITECTURE.md`, `SECURITY.md`, `FAILURE-MODES.md` and at least 4 ADRs are written
- [ ] Live demo is online with a seeded sandbox key
- [ ] README has: one-line pitch, demo link and GIF, features, architecture diagram, quick start, `curl` examples, benchmarks, known limits, roadmap

**ADRs to write**

1. Why Redis for limits and cache, and what happens when Redis is down
2. How placeholders are restored in streams
3. Why logs and traces hold redacted metadata only
4. How fallback affects cost accounting and retries

---

## 14. Decisions already made

- Language and framework: Python 3.12 + FastAPI.
- Public repo from early on (made public by the end of Phase 1). Secrets are scanned in CI from day one.
- Cache applies to **non-streaming** requests only in v1.
- Fallback for streams happens only before the first chunk is sent.
- Name: **Maskgate** (check availability on GitHub, PyPI/npm and as a domain before publishing).
- Project is positioned as a focused, privacy-first learning and portfolio project, not a replacement for existing gateways.

**Open questions to ask the developer when relevant**

- Redis unavailable: fail open (skip limits and cache) or fail closed (reject)? Default suggestion: fail open for cache, fail closed for budget checks.
- Which two real providers and models to ship in `models.yaml`?
- Where to host the public demo?

---

## 15. Quick start (target experience)

```bash
git clone https://github.com/<you>/maskgate && cd maskgate
cp .env.example .env
docker compose up --build

# create a key
curl -X POST localhost:8000/admin/keys \
  -H "X-Admin-Token: change-me" -H "Content-Type: application/json" \
  -d '{"name":"demo"}'

# normal request (mock provider, no real keys needed)
curl localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $MASKGATE_KEY" -H "Content-Type: application/json" \
  -d '{"model":"mock-fast","messages":[{"role":"user","content":"Hello"}]}'

# request containing synthetic private data: check X-Maskgate-PII-Count in the response headers
curl -i localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $MASKGATE_KEY" -H "Content-Type: application/json" \
  -d '{"model":"mock-fast","messages":[{"role":"user","content":"Email abel@example.com or call +251911000000"}]}'
```

`make` targets the agent should provide: `make up`, `make down`, `make test`, `make lint`, `make typecheck`, `make check` (lint + types + tests), `make migrate`, `make seed`, `make loadtest`.

---

## 16. Known limits (keep this section honest)

- PII detection is probabilistic. It will miss some values and flag some false positives. Measured results belong in `docs/SECURITY.md`.
- Redaction can reduce answer quality when the model needs the original value to reason about it.
- Only two real providers and chat completions are supported in v1.
- Cache is exact-match only.
- Single-region, single-instance reference deployment.
