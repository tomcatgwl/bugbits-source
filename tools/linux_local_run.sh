#!/usr/bin/env bash
# Run local experiments with task-owned writes inside the repository.
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$TASK_ROOT"
TASK_RUNTIME="$TASK_ROOT/tmp/linux/runtime"
TASK_CACHE="$TASK_ROOT/out/linux-continuation/cache"
mkdir -p -- "$TASK_RUNTIME" "$TASK_CACHE" "$TASK_ROOT/tmp/linux/config" \
  "$TASK_ROOT/tmp/linux/data" "$TASK_ROOT/tmp/linux/xdg-run"
chmod 700 -- "$TASK_ROOT/tmp/linux/xdg-run"
export TMPDIR="$TASK_RUNTIME" TMP="$TASK_RUNTIME" TEMP="$TASK_RUNTIME"
export XDG_CACHE_HOME="$TASK_CACHE"
export XDG_CONFIG_HOME="$TASK_ROOT/tmp/linux/config"
export XDG_DATA_HOME="$TASK_ROOT/tmp/linux/data"
export XDG_RUNTIME_DIR="$TASK_ROOT/tmp/linux/xdg-run"
export PYTHONDONTWRITEBYTECODE=1
export PIP_CACHE_DIR="$TASK_CACHE/pip"
# Explicitly read the already installed browsers; never install into this path.
export PLAYWRIGHT_BROWSERS_PATH="${BUGBITS_EXISTING_BROWSERS:-/home/ubuntu/.cache/ms-playwright}"
exec "$@"
