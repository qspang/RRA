#!/usr/bin/env bash
set -euo pipefail
OFFICE_PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OFFICE_TASK_ROOT="${ROAD_OFFICE_ROOT:-$OFFICE_PROJECT_ROOT/.tools/office/root}"
if [[ ! -x "$OFFICE_TASK_ROOT/usr/lib/libreoffice/program/soffice" ]]; then
  if command -v soffice >/dev/null 2>&1; then
    exec soffice "$@"
  fi
  echo '缺少Word预览环境，请运行 .venv/bin/python tools/prepare_office.py' >&2
  exit 127
fi
export LD_LIBRARY_PATH="$OFFICE_TASK_ROOT/usr/lib/libreoffice/program:$OFFICE_TASK_ROOT/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$OFFICE_TASK_ROOT/usr/lib/libreoffice/program/soffice" "$@"
