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
  echo '[配置提示] 缺少工作台页面 frontend_integration/route-planning-agent/dist/index.html，报告 API 仍可启动。' >&2
fi
config=configs/config.dapu-kml.json
if [[ ! -f $config ]]; then
  echo '[配置提示] 尚无 configs/config.dapu-kml.json，暂用公开模板。请复制 config.dapu-kml.example.json 为 config.dapu-kml.json，配置数据和 API 后重启。' >&2
  config=configs/config.dapu-kml.example.json
fi
exec .venv/bin/python -m road_description.service --config "$config" --jobs outputs/workbench_jobs --port "$port" --workbench
