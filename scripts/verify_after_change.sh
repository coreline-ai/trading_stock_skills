#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

cd "${ROOT_DIR}"

echo "[1/3] running regression tests"
"${PYTHON_BIN}" -m pytest -q \
  tests/test_engine_api_v2.py \
  tests/test_skill_traits.py \
  tests/test_dashboard_template.py \
  tests/test_dashboard_selection.py \
  tests/test_dashboard_visual_regression.py

echo "[2/3] restarting dashboard server"
HOST="${HOST}" PORT="${PORT}" "${ROOT_DIR}/scripts/dashboard_server.sh" restart

echo "[3/3] verifying dashboard endpoint"
if ! curl -fsS "http://${HOST}:${PORT}/dashboard" >/dev/null; then
  echo "dashboard verification failed: http://${HOST}:${PORT}/dashboard"
  exit 1
fi

echo "[4/4] full skill uniqueness audit"
if ! "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_full_skill_uniqueness_report.py"; then
  echo "skill uniqueness audit failed. see reports/diagnostics/latest_skill_uniqueness_report.{json,html}"
  exit 1
fi

echo "[5/5] full skill independence audit"
if ! "${PYTHON_BIN}" "${ROOT_DIR}/scripts/run_skill_independence_report.py"; then
  echo "skill independence audit failed. see reports/diagnostics/latest_skill_independence_report.{json,html}"
  exit 1
fi

echo "verify complete: tests + runtime health + uniqueness + independence audit OK"
