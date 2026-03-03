#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-restart}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-20}"
LOG_PATH="${LOG_PATH:-/tmp/trading_skills_${PORT}.log}"
PID_PATH="${PID_PATH:-/tmp/trading_skills_${PORT}.pid}"
HEALTH_URL="http://${HOST}:${PORT}/healthz"

# Runtime output defaults (keeps tracked reports/ files clean during local server runs)
SKILL_RUN_REPORT_V2_PATH="${SKILL_RUN_REPORT_V2_PATH:-${ROOT_DIR}/reports/runtime/latest_skill_runs_v2.runtime.json}"
AI_REPORT_PATH="${AI_REPORT_PATH:-${ROOT_DIR}/reports/runtime/latest_ai_report.runtime.json}"
AI_REPORT_RUNTIME_PATH="${AI_REPORT_RUNTIME_PATH:-${ROOT_DIR}/reports/runtime/ai_runtime.runtime.json}"

pick_python_bin() {
  local configured="${PYTHON_BIN:-}"
  if [[ -n "${configured}" ]]; then
    if [[ -x "${configured}" ]]; then
      echo "${configured}"
      return 0
    fi
    if command -v "${configured}" >/dev/null 2>&1; then
      command -v "${configured}"
      return 0
    fi
    echo "configured PYTHON_BIN is not executable: ${configured}" >&2
    return 1
  fi

  local candidates=(
    "${ROOT_DIR}/.venv/bin/python3.11"
    "${ROOT_DIR}/.venv/bin/python"
    "python3.11"
    "python3"
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
    if command -v "${candidate}" >/dev/null 2>&1; then
      command -v "${candidate}"
      return 0
    fi
  done
  return 1
}

python_runtime_reason() {
  local py_bin="$1"
  local version
  version="$("${py_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
  if [[ -z "${version}" ]]; then
    echo "failed to inspect python runtime: ${py_bin}"
    return 1
  fi
  local major="${version%%.*}"
  local minor="${version##*.}"
  if (( major < 3 || (major == 3 && minor < 11) )); then
    echo "python>=3.11 required, found ${version} (${py_bin})"
    return 1
  fi
  if ! "${py_bin}" -c "import uvicorn" >/dev/null 2>&1; then
    echo "uvicorn not found in ${py_bin}"
    return 1
  fi
  return 0
}

resolve_python_bin() {
  local configured="${PYTHON_BIN:-}"
  local reason=""
  if [[ -n "${configured}" ]]; then
    local selected
    selected="$(pick_python_bin)" || {
      echo "configured PYTHON_BIN is unavailable: ${configured}" >&2
      return 1
    }
    reason="$(python_runtime_reason "${selected}" || true)"
    if [[ -n "${reason}" ]]; then
      echo "${reason}" >&2
      echo "install deps with: ${selected} -m pip install -e '.[dev]'" >&2
      return 1
    fi
    echo "${selected}"
    return 0
  fi

  local candidates=(
    "${ROOT_DIR}/.venv/bin/python3.11"
    "${ROOT_DIR}/.venv/bin/python"
    "python3.11"
    "python3"
  )
  local candidate
  local last_reason="python runtime not found (tried .venv/bin/python3.11, .venv/bin/python, python3.11, python3)"
  for candidate in "${candidates[@]}"; do
    local resolved=""
    if [[ -x "${candidate}" ]]; then
      resolved="${candidate}"
    elif command -v "${candidate}" >/dev/null 2>&1; then
      resolved="$(command -v "${candidate}")"
    fi
    if [[ -z "${resolved}" ]]; then
      continue
    fi
    reason="$(python_runtime_reason "${resolved}" || true)"
    if [[ -z "${reason}" ]]; then
      echo "${resolved}"
      return 0
    fi
    last_reason="${reason}"
  done
  echo "${last_reason}" >&2
  return 1
}

port_pids() {
  lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true
}

is_healthy() {
  curl -fsS "${HEALTH_URL}" >/dev/null 2>&1
}

pid_is_alive() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1
}

pid_is_listening_on_port() {
  local pid="$1"
  [[ -n "${pid}" ]] || return 1
  lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | tr ' ' '\n' | grep -qx "${pid}"
}

wait_for_stop() {
  for _ in {1..30}; do
    if [[ -z "$(port_pids)" ]]; then
      return 0
    fi
    sleep 0.2
  done
  return 1
}

wait_for_start() {
  local pid="$1"
  for _ in $(seq 1 "${STARTUP_TIMEOUT}"); do
    if ! pid_is_alive "${pid}"; then
      return 1
    fi
    if is_healthy && pid_is_listening_on_port "${pid}"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

stop_server() {
  local pids
  pids="$(port_pids)"
  if [[ -n "${pids}" ]]; then
    kill ${pids} >/dev/null 2>&1 || true
  fi
  if [[ -f "${PID_PATH}" ]]; then
    local pid_file_value
    pid_file_value="$(cat "${PID_PATH}" 2>/dev/null || true)"
    if [[ -n "${pid_file_value}" ]] && kill -0 "${pid_file_value}" >/dev/null 2>&1; then
      kill "${pid_file_value}" >/dev/null 2>&1 || true
    fi
  fi
  if ! wait_for_stop; then
    pids="$(port_pids)"
    if [[ -n "${pids}" ]]; then
      kill -9 ${pids} >/dev/null 2>&1 || true
    fi
  fi
  rm -f "${PID_PATH}"
}

start_server() {
  cd "${ROOT_DIR}"
  if [[ -n "$(port_pids)" ]]; then
    echo "port ${PORT} already in use by pid(s): $(port_pids)"
    return 1
  fi
  local py_bin="${PYTHON_BIN:-}"
  if [[ -z "${py_bin}" ]]; then
    echo "internal error: PYTHON_BIN is empty"
    return 1
  fi
  mkdir -p "${ROOT_DIR}/reports/runtime"
  : >"${LOG_PATH}"
  nohup env \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}" \
    SKILL_RUN_REPORT_V2_PATH="${SKILL_RUN_REPORT_V2_PATH}" \
    AI_REPORT_PATH="${AI_REPORT_PATH}" \
    AI_REPORT_RUNTIME_PATH="${AI_REPORT_RUNTIME_PATH}" \
    "${py_bin}" -m uvicorn trading_skills_engine.web.app:app --host "${HOST}" --port "${PORT}" >>"${LOG_PATH}" 2>&1 </dev/null &
  local pid=$!
  echo "${pid}" >"${PID_PATH}"

  if wait_for_start "${pid}"; then
    echo "started pid=${pid} python=${py_bin} url=http://${HOST}:${PORT}/dashboard"
    return 0
  fi

  echo "healthcheck timeout url=${HEALTH_URL}"
  tail -n 120 "${LOG_PATH}" || true
  return 1
}

ensure_server() {
  if is_healthy; then
    echo "health=ok url=http://${HOST}:${PORT}/dashboard"
    return 0
  fi
  echo "health=fail -> restarting"
  stop_server
  start_server
}

status_server() {
  local pids
  pids="$(port_pids)"
  if [[ -z "${pids}" ]]; then
    if [[ -f "${PID_PATH}" ]]; then
      local stale_pid
      stale_pid="$(cat "${PID_PATH}" 2>/dev/null || true)"
      rm -f "${PID_PATH}"
      if [[ -n "${stale_pid}" ]]; then
        echo "stopped (removed stale pid file: ${stale_pid})"
        return 1
      fi
    fi
    echo "stopped"
    return 1
  fi
  if is_healthy; then
    echo "running pids=${pids} health=ok url=http://${HOST}:${PORT}/dashboard"
    return 0
  fi
  echo "running pids=${pids} health=fail"
  return 2
}

case "${ACTION}" in
  start)
    PYTHON_BIN="$(resolve_python_bin)" || exit 1
    if [[ -n "$(port_pids)" ]]; then
      echo "already running on ${HOST}:${PORT}"
      status_server
      exit 0
    fi
    start_server
    ;;
  stop)
    stop_server
    echo "stopped"
    ;;
  restart)
    PYTHON_BIN="$(resolve_python_bin)" || exit 1
    stop_server
    start_server
    ;;
  status)
    status_server
    ;;
  check)
    if is_healthy; then
      echo "health=ok"
      exit 0
    fi
    echo "health=fail"
    exit 1
    ;;
  ensure)
    PYTHON_BIN="$(resolve_python_bin)" || exit 1
    ensure_server
    ;;
  run)
    PYTHON_BIN="$(resolve_python_bin)" || exit 1
    cd "${ROOT_DIR}"
    mkdir -p "${ROOT_DIR}/reports/runtime"
    exec env \
      PYTHONUNBUFFERED=1 \
      PYTHONPATH="${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}" \
      SKILL_RUN_REPORT_V2_PATH="${SKILL_RUN_REPORT_V2_PATH}" \
      AI_REPORT_PATH="${AI_REPORT_PATH}" \
      AI_REPORT_RUNTIME_PATH="${AI_REPORT_RUNTIME_PATH}" \
      "${PYTHON_BIN}" -m uvicorn trading_skills_engine.web.app:app --host "${HOST}" --port "${PORT}"
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status|check|ensure|run}"
    exit 2
    ;;
esac
