# Runtime Status Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent transient or ambiguous model probe failures from appearing as false permanent outages, and make local startup/configuration deterministic.

**Architecture:** Keep the existing OpenAI-compatible `/models` probe, but return typed failure categories and timing metadata from the backend. Add live/readiness health endpoints and startup validation, then let the Vue badge require consecutive failures before showing offline. Standardize local ports through one PowerShell launcher without adding dependencies.

**Tech Stack:** FastAPI, Pydantic settings, httpx, pytest, Vue 3, TypeScript, Playwright, PowerShell.

---

### Task 1: Lock down probe error classification

**Files:**
- Modify: `backend/tests/test_runtime_status.py`
- Modify: `backend/evaluation/runtime_client.py`
- Modify: `backend/app/services/runtime/status.py`

- [x] **Step 1: Add failing tests** for timeout, HTTP 401, connection failure, missing model, and successful model response. Assert stable `error_code`, `status`, and sanitized endpoint.
- [x] **Step 2: Run `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_runtime_status.py -q` and confirm the new assertions fail against the current broad-exception implementation.
- [x] **Step 3: Implement a typed probe result and exception mapping. Use one retry only for timeout/connection errors, cap each request at 10 seconds, and never include API keys or response bodies in `detail`.
- [x] **Step 4: Run the same test command and confirm all runtime status tests pass.
- [x] **Step 5: Commit as `fix: classify model runtime probe failures`.

### Task 2: Expose complete runtime and readiness contracts

**Files:**
- Modify: `backend/app/api/v1/endpoints/runtime.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/tests/test_merge_readiness_unittest.py`
- Create: `backend/tests/test_health_endpoints.py`

- [x] **Step 1: Add failing tests** for `GET /health/live` returning 200, `GET /health/ready` returning 200/503, public runtime fields including endpoint/latency/error code, and startup validation rejecting missing DeepSeek API key or model.
- [x] **Step 2: Run the focused backend tests and confirm failure because the endpoints/fields/validation do not exist.
- [x] **Step 3: Implement `/health/live` and `/health/ready`; keep `/health` backward-compatible as liveness. Add optional response fields (`error_code`, `latency_ms`, `last_success_at`, `endpoint`) while retaining runtime route authentication.
- [x] **Step 4: Add provider-aware settings validation that runs only for explicit production/readiness checks and does not print secrets. Keep development SQLite behavior unchanged.
- [x] **Step 5: Run the focused backend tests and confirm they pass.
- [x] **Step 6: Commit as `feat: add model readiness and health contracts`.

### Task 3: Make the frontend status state machine tolerant

**Files:**
- Modify: `frontend/src/api/runtime.ts`
- Modify: `frontend/src/components/layout/OpenClawBadge.vue`
- Modify: `frontend/tests/runtime-status.spec.ts`
- Modify: `frontend/tests/enterprise-ui.spec.ts`
- Create: `frontend/src/utils/runtime-status.ts`
- Create: `frontend/tests/runtime-status-machine.spec.ts`

- [x] **Step 1: Add failing unit tests** for `checking`, single failure as `degraded`, consecutive failures as `offline`, recovery to `online`, and safe error text mapping.
- [x] **Step 2: Run `npm.cmd --prefix frontend exec playwright test frontend/tests/runtime-status-machine.spec.ts frontend/tests/runtime-status.spec.ts` and confirm failure because the state machine helper does not exist.
- [x] **Step 3: Implement the small pure state-machine helper and extend `RuntimeStatus` with optional backend metadata.
- [x] **Step 4: Update `OpenClawBadge.vue` to preserve the last online model during one failed poll, show retrying/degraded state, and only show offline after two consecutive failures. Keep the 30-second polling interval and avoid sensitive details.
- [x] **Step 5: Run focused frontend tests, then type-check with `npm.cmd --prefix frontend run type-check`.
- [x] **Step 6: Commit as `fix: prevent transient runtime outage misreports`.

### Task 4: Standardize local startup and prevent port drift

**Files:**
- Create: `scripts/dev.ps1`
- Modify: `README.md`
- Create: `scripts/tests/test_dev_script.ps1`

- [ ] **Step 1: Add a script contract test** that checks the launcher fixes frontend port 5173, backend port 8000, honors `VITE_API_PROXY_TARGET`, and refuses an occupied port with an actionable message.
- [ ] **Step 2: Run the script contract test and confirm failure because no launcher exists.
- [ ] **Step 3: Implement `scripts/dev.ps1` using existing Python/Vite commands only; do not install packages, kill processes, or overwrite `.env`. The script checks ports before starting and prints the selected backend target.
- [ ] **Step 4: Update README local-start instructions to use the launcher and document that `.env` changes require backend restart.
- [ ] **Step 5: Run the script contract test and inspect `git diff --check`.
- [ ] **Step 6: Commit as `chore: standardize local service startup`.

### Task 5: Full regression and acceptance

**Files:**
- Modify: `docs/superpowers/specs/2026-09-11-runtime-status-reliability-design.md` only if acceptance wording needs correction.

- [ ] **Step 1: Run focused backend and frontend tests for all changed seams.
- [ ] **Step 2: Start one backend on 8000 and one frontend on 5173 with the launcher, log in using the seeded development account, and verify the badge shows the configured provider/model.
- [ ] **Step 3: Exercise readiness failure with a temporary process-level endpoint override; verify 503 and a classified error without exposing secrets. Restore the original running configuration.
- [ ] **Step 4: Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\\scripts\\quality_gate.ps1` from `a03-contract-audit` and require exit code 0.
- [ ] **Step 5: Run the full Playwright suite with the local site and verify desktop, mobile, online, degraded, offline, and recovery states.
- [ ] **Step 6: Review `git diff`, `git status --short`, and committed file list; confirm no `.env`, keys, databases, logs, or outputs are tracked.
- [ ] **Step 7: Commit the final verification/documentation adjustment only when required, then report exact test evidence.
