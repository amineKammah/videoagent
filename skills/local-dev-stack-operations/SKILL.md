---
name: local-dev-stack-operations
description: Install, run, and troubleshoot the local VideoAgent development stack (Cloud SQL proxy, backend API, frontend app). Use when setting up a machine, booting services, diagnosing startup failures, validating required environment variables, or stabilizing local dev loops.
---

# Local Dev Stack Operations

## Quick Start
- Open `references/local-dev-stack-runbook.md`.
- Prefer `./dev_stack.sh install` then `./dev_stack.sh run` from repo root.
- Use standalone backend/frontend commands only for targeted debugging.

## Standard Procedure
1. Install dependencies.
- Create/refresh Python venv and install backend editable package.
- Install frontend `node_modules`.
2. Validate environment.
- Ensure `.env` exists and contains Cloud SQL and DB connection settings for local run.
3. Start stack.
- Start Cloud SQL proxy, backend API, and frontend dev server via `dev_stack.sh`.
4. Confirm health.
- Backend docs reachable at `http://localhost:8000/docs`.
- Frontend reachable at `http://localhost:3000`.
5. Run focused checks when unstable.
- Backend smoke tests and targeted verify scripts.

## Troubleshooting Priorities
- Missing command errors (`python3`, `npm`, `cloud-sql-proxy`).
- Missing env vars (`CLOUD_SQL_INSTANCE_CONNECTION_NAME`, DB settings).
- venv or node_modules absent.
- Process exits in proxy/backend/frontend loops.
- Port conflicts and stale processes.

## Guardrails
- Avoid ad-hoc startup commands before validating env prerequisites.
- Keep backend and frontend versions aligned with repo READMEs.
- Prefer single source of truth (`dev_stack.sh`) for team onboarding.
