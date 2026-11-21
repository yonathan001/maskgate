# Project Progress

## Phase 1: Skeleton and first request
- **Status:** Complete (Acceptance criteria passed)
- **Done:**
  - Repo scaffolding: `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.example`, `.gitignore`, `LICENSE`, CI workflow.
  - Configuration via `pydantic-settings`.
  - Database schema & Alembic migration (`api_keys`, `requests`, `audit_log`, `provider_health`).
  - Auth module with SHA-256 key hashing and constant-time key lookup.
  - Admin endpoints (`/admin/keys`, `/admin/usage`, `/admin/requests`, `/admin/providers`, `/admin/demo/provider-down`).
  - Mock provider and registry (`models.yaml`).
  - OpenAI-compatible `/v1/chat/completions` (non-streaming) and `/v1/models`.
  - Official OpenAI Python SDK compatibility integration test.
  - Health check endpoint `/health`.
  - Strict type checking (`mypy app`) and linting/formatting (`ruff check`, `ruff format`).
- **Decisions made:**
  - Used `CompatibleArray` and `CompatibleJSON` with SQLite/Postgres variant support for seamless local and containerized testing.
  - Formatted OpenAI-shaped error responses with `message`, `type`, and `code`.
  - Requests never log raw prompts or responses (only metadata recorded).
- **Open questions:**
  - None. Acceptance criteria passed.

## Phase 2: Real providers, retries, fallback
- **Status:** Complete (Acceptance criteria passed)
- **Done:**
  - Implemented `OpenAIProvider` adapter with error normalization (429, 5xx, timeouts, network, 4xx).
  - Implemented `AnthropicProvider` adapter translating messages and top-level system prompts.
  - Implemented `RequestPipeline` with per-attempt timeout, exponential backoff with jitter, retryable vs non-retryable error handling, and provider route failover.
  - Implemented provider health tracking recorded to PostgreSQL.
  - Added unit test suite for adapters with RESPX (`test_providers.py`).
  - Added comprehensive integration tests (`test_fallback.py`) covering: 500 retry and success, 429 retry, fallback across providers, 4xx non-retry, and 502 when all providers fail.
- **Decisions made:**
  - Non-retryable 4xx client errors immediately stop retries on the current provider and fail over or return appropriate errors.
  - Provider health is updated in `provider_health` table upon success or exhausted retry failures.
- **Open questions:**
  - None. Acceptance criteria passed.

## Phase 3: Cost, limits, budgets
- **Status:** Complete (Acceptance criteria passed)
- **Done:**
  - Implemented exact token-to-cost calculation (`calculate_cost`) in `gateway/app/core/cost.py`.
  - Implemented `LimitManager` in `gateway/app/core/limits.py` with fixed-window rate limiting (`INCR` + `EXPIRE`), returning `429` with `Retry-After`.
  - Implemented monthly spend tracking and budget enforcement (`402 BudgetExhaustedError`), mirrored in Redis and reconciled from PostgreSQL.
  - Implemented startup counter reconciliation in FastAPI lifespan (`gateway/app/main.py`).
  - Added unit tests for cost math with Decimal precision (`test_cost.py`) and limit manager (`test_limits.py`).
  - Added integration tests (`test_budget_and_limits.py`) verifying 429 on rate limit, 402 on budget exhausted, and counter reconciliation across cache resets.
  - Verified `GET /admin/usage` endpoint functionality.
- **Decisions made:**
  - Per ADR 1: rate limiter fails open on Redis error; budget checks fail closed or fall back to PostgreSQL.
  - Used `InMemoryRedis` store to enable fast, zero-dependency testing and resilient fallback.
- **Open questions:**
  - None. Acceptance criteria passed.

## Phase 4: Cache and streaming
- **Status:** Complete (Acceptance criteria passed)
- **Done:**
  - Implemented deterministic canonical JSON cache key builder and `ResponseCache` in `gateway/app/core/cache.py`.
  - Integrated cache lookup & storage in `/v1/chat/completions` for non-streaming requests with `temperature == 0.0`.
  - Implemented SSE streaming pass-through (`stream: true`) with standard OpenAI chunk formatting and final `data: [DONE]`.
  - Implemented streaming fallback before first chunk is sent, and graceful error event emission if a stream drops midway.
  - Added unit tests for cache key canonicalization, temperature gating, and get/set (`test_cache.py`).
  - Added integration tests (`test_cache_and_streaming.py`) verifying cache hits, streaming delivery, midway stream interruption handling, and streaming failover.
- **Decisions made:**
  - Cache applies to deterministic requests (`temperature=0.0` or `None`) for non-streaming calls.
  - Fallback is permitted before the first chunk is sent; once streaming starts, midway failures emit an SSE error event and end cleanly.
- **Open questions:**
  - None. Acceptance criteria passed.

## Phase 5: PII Redaction
- **Status:** Complete (Acceptance criteria passed)
- **Done:**
  - Implemented `RedactionEngine` using Microsoft Presidio (`en_core_web_sm`) and custom recognizers.
  - Implemented custom recognizers in `gateway/app/redaction/recognizers.py` (`EthiopianPhoneRecognizer` for international & national formats, `NationalIdRecognizer` for generic alphanumeric IDs).
  - Implemented `StreamRestorer` in `gateway/app/redaction/stream.py` with sliding tail buffer ensuring placeholders split across arbitrary chunk boundaries are reconstructed and restored without leaking placeholders or raw data.
  - Integrated redaction engine and stream restorer in `gateway/app/api/v1.py`:
    - Incoming messages are redacted before cache lookup and provider transmission.
    - Deterministic cache stores sanitized text.
    - Upstream provider receives only sanitized prompt text.
    - Outgoing responses restore original values seamlessly (non-streaming and streaming SSE).
    - Sets `X-Maskgate-PII-Count` response header.
  - Documented threat model, redaction pipeline, and security invariants in `docs/SECURITY.md`.
  - Added test suite:
    - `test_recognizers.py`: Matches and negative cases for Ethiopian phone numbers and National IDs.
    - `test_redaction_engine.py`: Single & repeated entity redaction, disabled redaction passthrough, bidirectionality.
    - `test_stream_restorer.py`: Property test slicing placeholders at every possible character boundary and single-character chunks.
    - `test_privacy_zero_leak.py`: Proves synthetic PII names, emails, phones, and IDs are never transmitted to upstream providers or persisted to database tables.
- **Decisions made:**
  - Configured Presidio explicitly with lightweight `en_core_web_sm` to avoid 380MB spacy model download hangs.
  - Tail buffer in `StreamRestorer` holds trailing bytes up to `max(len(placeholder)) - 1` to prevent premature emission of split placeholder tokens.
  - Cache stores sanitized text; placeholder restoration runs on cache hit against current request mapping.
- **Open questions:**
  - None. Acceptance criteria passed.
