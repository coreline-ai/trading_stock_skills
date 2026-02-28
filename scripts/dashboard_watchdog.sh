#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-start}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"
INTERVAL_SEC="${INTERVAL_SEC:-15}"
WATCHDOG_LOG_PATH="${WATCHDOG_LOG_PATH:-/tmp/trading_skills_watchdog_${PORT}.log}"
WATCHDOG_PID_PATH="${WATCHDOG_PID_PATH:-/tmp/trading_skills_watchdog_${PORT}.pid}"

start_watchdog() {
  if [[ -f "${WATCHDOG_PID_PATH}" ]]; then
    local existing_pid
    existing_pid="$(cat "${WATCHDOG_PID_PATH}" 2>/dev/null || true)"
    if [[ -n "${existing_pid}" ]] && kill -0 "${existing_pid}" >/dev/null 2>&1; then
      echo "watchdog already running pid=${existing_pid}"
      return 0
    fi
  fi

  : >"${WATCHDOG_LOG_PATH}"
  nohup bash -c "
    set -euo pipefail
    while true; do
      if ! HOST='${HOST}' PORT='${PORT}' '${ROOT_DIR}/scripts/dashboard_server.sh' check >/dev/null 2>&1; then
        echo \"[\$(date '+%Y-%m-%d %H:%M:%S')] healthcheck failed, restarting\" >> '${WATCHDOG_LOG_PATH}'
        HOST='${HOST}' PORT='${PORT}' '${ROOT_DIR}/scripts/dashboard_server.sh' restart >> '${WATCHDOG_LOG_PATH}' 2>&1 || true
      fi
      sleep '${INTERVAL_SEC}'
    done
  " >>"${WATCHDOG_LOG_PATH}" 2>&1 </dev/null &

  local pid=$!
  echo "${pid}" >"${WATCHDOG_PID_PATH}"
  echo "watchdog started pid=${pid} interval=${INTERVAL_SEC}s log=${WATCHDOG_LOG_PATH}"
}

stop_watchdog() {
  if [[ ! -f "${WATCHDOG_PID_PATH}" ]]; then
    echo "watchdog stopped"
    return 0
  fi
  local pid
  pid="$(cat "${WATCHDOG_PID_PATH}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}" >/dev/null 2>&1 || true
  fi
  rm -f "${WATCHDOG_PID_PATH}"
  echo "watchdog stopped"
}

status_watchdog() {
  if [[ ! -f "${WATCHDOG_PID_PATH}" ]]; then
    echo "watchdog not running"
    return 1
  fi
  local pid
  pid="$(cat "${WATCHDOG_PID_PATH}" 2>/dev/null || true)"
  if [[ -n "${pid}" ]] && kill -0 "${pid}" >/dev/null 2>&1; then
    echo "watchdog running pid=${pid} interval=${INTERVAL_SEC}s log=${WATCHDOG_LOG_PATH}"
    return 0
  fi
  echo "watchdog not running (stale pid file)"
  return 1
}

case "${ACTION}" in
  start)
    start_watchdog
    ;;
  stop)
    stop_watchdog
    ;;
  restart)
    stop_watchdog
    start_watchdog
    ;;
  status)
    status_watchdog
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status}"
    exit 2
    ;;
esac

