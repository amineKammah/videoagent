# Local Dev Stack Runbook

## Table of Contents
- Primary entrypoint
- Install path
- Run path
- Required environment
- Service checks
- Fallback commands

## Primary Entrypoint
- Use orchestrated script from repo root: `dev_stack.sh:1`.
- Supported commands:
- `./dev_stack.sh install`: `dev_stack.sh:12`
- `./dev_stack.sh run`: `dev_stack.sh:13`

## Install Path
- Verifies required binaries and installs dependencies: `dev_stack.sh:47`.
- Creates local `.venv` and installs backend editable package: `dev_stack.sh:61`.
- Installs frontend dependencies in `videoagent-studio`: `dev_stack.sh:70`.

## Run Path
- Requires existing `.venv` and frontend `node_modules`: `dev_stack.sh:82`.
- Loads `.env` automatically if present: `dev_stack.sh:38`.
- Requires `CLOUD_SQL_INSTANCE_CONNECTION_NAME`: `dev_stack.sh:94`.
- Optionally builds `DATABASE_URL` from `DB_USER/DB_PASSWORD/DB_NAME`: `dev_stack.sh:106`.
- Starts proxy, backend, and frontend and monitors all three PIDs: `dev_stack.sh:127`.

## Required Environment
- Root prerequisites and env expectations: `README.md:7`.
- Backend runtime and test commands: `backend/README.md:13`.
- Frontend API base override using `.env.local`: `videoagent-studio/README.md:24`.

## Service Checks
- Backend launcher and uvicorn settings: `backend/scripts/run_api.py:9`.
- Backend docs expected at `http://localhost:8000/docs`: `backend/README.md:27`.
- Frontend default URL expected at `http://localhost:3000`: `videoagent-studio/README.md:39`.

## Fallback Commands
- Backend direct run: `python3 backend/scripts/run_api.py`.
- Frontend direct run: `npm run dev` in `/videoagent-studio`.
- Basic backend tests: `python3 backend/scripts/run_basic_tests.py`.
