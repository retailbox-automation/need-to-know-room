#!/usr/bin/env bash
# Switch's agent controller, which runs the Claude Code desk (Tier B).
#
#   ./scripts/controller.sh install   download switch-agent-controller 0.31.0 into .stand/controller
#   ./scripts/controller.sh enroll    enroll this machine with the local stack (one-time code)
#   ./scripts/controller.sh start     run it in the background (log: .stand/logs/controller.log)
#   ./scripts/controller.sh stop | status | doctor
#
# Needs .stand/agents.env (mode 600) with one line:
#   CLAUDE_CODE_OAUTH_TOKEN=<token from `claude setup-token`>
#
# The controller, and every agent it starts, runs with HOME=.stand/desk-home and
# a minimal environment. That home is empty, so the desk's Claude Code sees none
# of your own ~/.claude: no settings, hooks, MCP servers, memory or history.
# The controller credential is kept in a file in .stand/controller-data, not in
# your keychain. Nothing is installed as a service.
set -euo pipefail

VERSION="0.31.0"
ASSET="https://github.com/sandbox-quantum/switch/releases/download/switch-agent-controller-v${VERSION}/switch-agent-controller-${VERSION}.tgz"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAND="${ROOT}/.stand"
PREFIX="${STAND}/controller"
BIN="${PREFIX}/node_modules/.bin/switch-agent-controller"
DATA="${STAND}/controller-data"
DESK_HOME="${STAND}/desk-home"
ENV_FILE="${STAND}/agents.env"
LOG="${STAND}/logs/controller.log"
PIDFILE="${STAND}/controller.pid"

need_stack() {
  [ -s "${STAND}/.env" ] || { echo "Start the stack first: ./scripts/up.sh" >&2; exit 1; }
  API_PORT="$(sed -n 's/^API_HOST_PORT=//p' "${STAND}/.env")"
}

# The agents' environment: an empty home and only what a CLI needs to run.
mkdir -p "$DESK_HOME"; chmod 700 "$STAND" "$DESK_HOME"
CLEAN=(env -i HOME="$DESK_HOME" PATH="$PATH" USER="${USER:-$(id -un)}" LOGNAME="${USER:-$(id -un)}"
       SHELL=/bin/bash LANG="${LANG:-en_US.UTF-8}" TMPDIR="${TMPDIR:-/tmp}")

need_env_file() {
  [ -s "$ENV_FILE" ] || { echo "Missing $ENV_FILE (CLAUDE_CODE_OAUTH_TOKEN=...); see agents/desk/README.md" >&2; exit 1; }
  grep -q '^CLAUDE_CODE_OAUTH_TOKEN=.' "$ENV_FILE" || { echo "$ENV_FILE has no CLAUDE_CODE_OAUTH_TOKEN" >&2; exit 1; }
  chmod 600 "$ENV_FILE"
}

need_bin() { [ -x "$BIN" ] || { echo "Run: ./scripts/controller.sh install" >&2; exit 1; }; }

running_pid() {  # prints the pid only if it is our controller
  [ -s "$PIDFILE" ] || return 1
  local pid; pid="$(cat "$PIDFILE")"
  ps -p "$pid" -o command= 2>/dev/null | grep -qF -- " run --data-dir ${DATA} " || return 1
  echo "$pid"
}

case "${1:-}" in
  install)
    node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22||(a===22&&b>=13)?0:1)' \
      || { echo "Node 22.13 or later is required (found $(node --version))" >&2; exit 1; }
    mkdir -p "$PREFIX"
    curl -fsSL "$ASSET" -o "${PREFIX}/controller.tgz"
    npm install --prefix "$PREFIX" --no-audit --no-fund --silent "${PREFIX}/controller.tgz"
    echo "installed: $("$BIN" --version 2>/dev/null || echo "$BIN")"
    ;;
  enroll)
    need_bin; need_stack
    code="$(python3 - "$ROOT/scripts" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from switchlib import Stand
print(Stand().gw("POST", "/management/enrollment-codes")["code"])
PY
)"
    mkdir -p "$DATA"; chmod 700 "$DATA"
    "${CLEAN[@]}" "$BIN" enroll --server "http://127.0.0.1:${API_PORT}" --code "$code" \
      --name n2k-desk --description "Need-to-Know Room: runs the desk agent" \
      --data-dir "$DATA" --secret-store file
    ;;
  start)
    need_bin; need_env_file
    if pid="$(running_pid)"; then echo "already running (pid $pid)"; exit 0; fi
    mkdir -p "$(dirname "$LOG")"
    nohup "${CLEAN[@]}" "$BIN" run --data-dir "$DATA" --env-file "$ENV_FILE" >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 3
    running_pid >/dev/null || { echo "controller exited; see $LOG" >&2; tail -20 "$LOG" >&2; exit 1; }
    echo "controller running (pid $(cat "$PIDFILE")), log: $LOG"
    ;;
  stop)
    if pid="$(running_pid)"; then kill "$pid"; echo "stopped (pid $pid)"; else echo "not running"; fi
    rm -f "$PIDFILE"
    ;;
  status) need_bin; "${CLEAN[@]}" "$BIN" status --data-dir "$DATA" ;;
  doctor) need_bin; need_env_file; "${CLEAN[@]}" "$BIN" doctor --data-dir "$DATA" --env-file "$ENV_FILE" ;;
  *) echo "usage: $0 install|enroll|start|stop|status|doctor" >&2; exit 2 ;;
esac
