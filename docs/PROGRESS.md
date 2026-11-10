# Project Progress

## Phase 1: Skeleton and first request
- **Status:** In Progress
- **Done:**
  - Repo scaffolding: `pyproject.toml`, `Makefile`, `docker-compose.yml`, `.env.example`, `.gitignore`, `LICENSE`, CI workflow.
  - Configuration via `pydantic-settings`.
  - Database schema & Alembic migration (`api_keys`, `requests`, `audit_log`, `provider_health`).
  - Auth module with SHA-256 key hashing and constant-time comparison.
  - Admin endpoints (`/admin/keys`, `/admin/usage`, `/admin/requests`, `/admin/providers`, `/admin/demo/provider-down`).
  - Mock provider and registry (`models.yaml`).
  - OpenAI-compatible `/v1/chat/completions` (non-streaming) and `/v1/models`.
  - Health check endpoint `/health`.
- **Decisions made:**
  - SQLite vs PostgreSQL: tests can run against PostgreSQL or test DB, with async engine compatibility.
  - Error responses strictly adhere to OpenAI format with `error.message`, `error.type`, and `error.code`.
- **Open questions:**
  - None for Phase 1.
