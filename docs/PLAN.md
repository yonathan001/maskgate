# Maskgate - Internal Build Plan & Agent Specification

> **Note:** This document preserves the full multi-phase implementation roadmap, instructions, and acceptance criteria for the Maskgate engineering team.

---

## 0. Instructions for the coding agent

Quality, tests, and honesty matter more than feature count.

**Working protocol**

1. Work **one phase at a time** (section 9). Do not start a phase until the previous phase's acceptance criteria pass.
2. Before coding a phase, restate its goal and list the files you will create or change.
3. Write tests **with** the code, not after. For redaction (Phase 5), write the tests first.
4. After each phase: run `make check` (lint, types, tests), fix failures, then update `docs/PROGRESS.md` with what was done, what was decided and what is still open.
5. Commit small and often using Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). One logical change per commit.
6. If a requirement is ambiguous or a decision would change the architecture, stop and ask instead of guessing.
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

---

## 4. Architecture & Pipeline

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

1. **Auth:** hash bearer key (SHA-256), look it up, reject if missing or inactive (`401`).
2. **Limits:** Redis rate limit (requests per minute) and monthly budget check (`429` / `402`).
3. **Redact:** detect private values in message `content`, replace with placeholders (`<PERSON_1>`, `<EMAIL_1>`...), keep map in memory only.
4. **Cache:** non-streaming only. SHA-256 of canonical JSON. Skip when `temperature > 0`.
5. **Provider call:** per-attempt timeout, up to 2 retries with exponential backoff + jitter on 5xx/429/timeouts. Never retry 4xx client errors. Fall back to next provider in model's order.
6. **Restore:** replace placeholders in response text with original values.
7. **Record:** write `requests` row (redacted metadata only), update cost and budgets, emit metrics.

---

## 5. Build plan (8 phases)

### Phase 1: Skeleton and first request
- Scaffold repo, Makefile, Docker, docker-compose, CI, .env.example, .gitignore.
- Config, DB models + Alembic migration, API key creation via admin API with hashed storage.
- Mock provider and non-streaming `/v1/chat/completions` (OpenAI format).
- **Acceptance:** `docker compose up` starts cleanly, OpenAI Python client works, CI is green.

### Phase 2: Real providers, retries, fallback
- OpenAI and Anthropic adapters with error normalization.
- Timeouts, retries with backoff and jitter, fallback to next provider.
- Provider health tracking and `/health`.
- **Acceptance:** Fallback returns `X-Maskgate-Fallback: true`, 4xx not retried, 5xx/429/timeouts retried.

### Phase 3: Cost, limits, budgets
- Token usage extraction, cost calculation from `models.yaml`.
- Redis rate limiting and monthly budget enforcement.
- `GET /admin/usage`.
- **Acceptance:** 429 on rate limit, 402 on budget, counters survive restarts.

### Phase 4: Cache and streaming
- Exact-match cache for non-streaming requests.
- SSE streaming pass-through (`stream: true`) with OpenAI chunk format and `[DONE]`.
- Streaming fallback before first chunk.
- **Acceptance:** Deterministic requests hit cache, streaming streams smoothly without hangs.

### Phase 5: PII redaction (write tests first)
- Redaction engine, custom recognizers (e.g. Ethiopian phone numbers, generic national IDs).
- Restoration and placeholder-safe stream restorer.
- **Acceptance:** Privacy tests pass (zero leaks to upstream, logs, traces, or DB).

### Phase 6: Observability and dashboard
- Request log, audit log, OTel spans and Prometheus metrics.
- Next.js dashboard.
- **Acceptance:** Dashboard shows live metrics; traces have zero PII.

### Phase 7: Failure and load testing
- Failure suite in `docs/FAILURE-MODES.md`.
- k6 scripts in `load-test/k6/` measuring gateway overhead.
- Raw results saved in `load-test/results/`.

### Phase 8: Release
- Public demo deployment with seeded sandbox key.
- Complete documentation (`ARCHITECTURE.md`, `SECURITY.md`, ADRs).
- Tag `v0.1.0`.
