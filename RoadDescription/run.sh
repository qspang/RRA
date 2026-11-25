#!/usr/bin/env bash
# Run the three report agents and their integrated web UI on one loopback port.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
port=${1:-11079}
if [[ $# -gt 1 || ! $port =~ ^[1-9][0-9]{0,4}$ ]] || (( port > 65535 )); then
  echo '用法：bash RoadDescription/run.sh [端口号 1-65535]' >&2
  exit 2
fi
if [[ ! -f frontend_integration/route-planning-agent/dist/index.html ]]; then
  echo '缺少工作台前端 frontend_integration/route-planning-agent/dist/index.html' >&2
  exit 1
fi
exec .venv/bin/python -m road_description.service --config configs/config.dapu-kml.json --jobs outputs/workbench_jobs --port "$port" --workbench
