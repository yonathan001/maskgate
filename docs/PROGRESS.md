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
