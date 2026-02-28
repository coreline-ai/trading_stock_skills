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

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

port_pids() {
  lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true
}

is_healthy() {
  curl -fsS "${HEALTH_URL}" >/dev/null 2>&1
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
  : >"${LOG_PATH}"
  nohup env PYTHONUNBUFFERED=1 "${PYTHON_BIN}" -m uvicorn trading_skills_engine.web.app:app --host "${HOST}" --port "${PORT}" >>"${LOG_PATH}" 2>&1 </dev/null &
  local pid=$!
  echo "${pid}" >"${PID_PATH}"

  for _ in $(seq 1 "${STARTUP_TIMEOUT}"); do
    if is_healthy; then
      echo "started pid=${pid} url=http://${HOST}:${PORT}/dashboard"
      return 0
    fi
    if ! kill -0 "${pid}" >/dev/null 2>&1; then
      echo "server exited early pid=${pid}"
      tail -n 120 "${LOG_PATH}" || true
      return 1
    fi
    sleep 1
  done

  echo "healthcheck timeout url=${HEALTH_URL}"
  tail -n 120 "${LOG_PATH}" || true
  return 1
}

status_server() {
  local pids
  pids="$(port_pids)"
  if [[ -z "${pids}" ]]; then
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
  *)
    echo "usage: $0 {start|stop|restart|status|check}"
    exit 2
    ;;
esac
