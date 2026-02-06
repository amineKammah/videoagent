#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
FRONTEND_DIR="${ROOT_DIR}/videoagent-studio"
BACKEND_DIR="${ROOT_DIR}/backend"

print_usage() {
  cat <<'EOF'
Usage:
  ./dev_stack.sh install
  ./dev_stack.sh run

Commands:
  install   Install backend/frontend dependencies into local .venv and node_modules.
  run       Start Cloud SQL proxy tunnel, backend API, and frontend dev server.

Required env vars for `run` (in .env or shell):
  CLOUD_SQL_INSTANCE_CONNECTION_NAME   e.g. my-project:us-central1:videoagent-db

Optional env vars for `run`:
  CLOUD_SQL_PROXY_CREDENTIALS_FILE     path to service-account json for DB project
  CLOUD_SQL_PROXY_PORT                 default: 5432
  DATABASE_URL                         if unset, can be built from DB_* vars
  DB_USER / DB_PASSWORD / DB_NAME      used only when DATABASE_URL is missing
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    exit 1
  fi
}

load_env_if_present() {
  if [[ -f "${ROOT_DIR}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${ROOT_DIR}/.env"
    set +a
  fi
}

install_all() {
  require_cmd python3
  require_cmd npm

  if ! command -v cloud-sql-proxy >/dev/null 2>&1; then
    if command -v brew >/dev/null 2>&1; then
      echo "Installing cloud-sql-proxy via Homebrew..."
      brew install cloud-sql-proxy
    else
      echo "cloud-sql-proxy is not installed. Install it first: https://cloud.google.com/sql/docs/postgres/connect-auth-proxy" >&2
      exit 1
    fi
  fi

  if [[ ! -d "${VENV_DIR}" ]]; then
    python3 -m venv "${VENV_DIR}"
  fi

  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"
  python -m pip install --upgrade pip
  python -m pip install -e "${BACKEND_DIR}"

  (
    cd "${FRONTEND_DIR}"
    npm install
  )

  echo "Install complete."
}

run_stack() {
  require_cmd npm
  require_cmd cloud-sql-proxy

  if [[ ! -d "${VENV_DIR}" ]]; then
    echo "Python virtualenv not found at ${VENV_DIR}. Run: ./dev_stack.sh install" >&2
    exit 1
  fi

  if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
    echo "Frontend dependencies missing. Run: ./dev_stack.sh install" >&2
    exit 1
  fi

  load_env_if_present

  if [[ -z "${CLOUD_SQL_INSTANCE_CONNECTION_NAME:-}" ]]; then
    echo "CLOUD_SQL_INSTANCE_CONNECTION_NAME is required." >&2
    exit 1
  fi

  local proxy_port="${CLOUD_SQL_PROXY_PORT:-5432}"
  local proxy_args=("${CLOUD_SQL_INSTANCE_CONNECTION_NAME}" "--port" "${proxy_port}")

  if [[ -n "${CLOUD_SQL_PROXY_CREDENTIALS_FILE:-}" ]]; then
    proxy_args+=("--credentials-file" "${CLOUD_SQL_PROXY_CREDENTIALS_FILE}")
  fi

  if [[ -z "${DATABASE_URL:-}" ]] && [[ -n "${DB_USER:-}" ]] && [[ -n "${DB_PASSWORD:-}" ]] && [[ -n "${DB_NAME:-}" ]]; then
    export DATABASE_URL="postgresql+psycopg://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${proxy_port}/${DB_NAME}"
  fi

  local p_proxy=""
  local p_backend=""
  local p_frontend=""

  cleanup() {
    local code=$?
    trap - EXIT INT TERM
    for pid in "${p_proxy}" "${p_backend}" "${p_frontend}"; do
      if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
        kill "${pid}" >/dev/null 2>&1 || true
      fi
    done
    wait >/dev/null 2>&1 || true
    exit "${code}"
  }
  trap cleanup EXIT INT TERM

  echo "Starting Cloud SQL proxy on port ${proxy_port}..."
  cloud-sql-proxy "${proxy_args[@]}" &
  p_proxy=$!

  echo "Starting backend API on http://localhost:8000 ..."
  (
    cd "${ROOT_DIR}"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    export PYTHONPATH="${BACKEND_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"
    python "${BACKEND_DIR}/scripts/run_api.py"
  ) &
  p_backend=$!

  echo "Starting frontend on http://localhost:3000 ..."
  (
    cd "${FRONTEND_DIR}"
    npm run dev
  ) &
  p_frontend=$!

  echo "All services started. Press Ctrl+C to stop."
  while true; do
    if ! kill -0 "${p_proxy}" >/dev/null 2>&1; then
      echo "Cloud SQL proxy exited unexpectedly." >&2
      exit 1
    fi
    if ! kill -0 "${p_backend}" >/dev/null 2>&1; then
      echo "Backend exited unexpectedly." >&2
      exit 1
    fi
    if ! kill -0 "${p_frontend}" >/dev/null 2>&1; then
      echo "Frontend exited unexpectedly." >&2
      exit 1
    fi
    sleep 1
  done
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    install)
      install_all
      ;;
    run)
      run_stack
      ;;
    *)
      print_usage
      exit 1
      ;;
  esac
}

main "${1:-}"
