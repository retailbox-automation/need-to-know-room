#!/usr/bin/env bash
# One command that checks the whole workflow on a seeded stack.
#
#   ./scripts/verify.sh         start keeper (and the scripted desk, unless a
#                               Claude Code desk is seeded), play every scene,
#                               then compare Switch's record with keeper's log
#   ./scripts/verify.sh stop    stop the keeper and desk it started
#
# Exit code 0 only if every scene passes and the audit finds no mismatch.
# Agent logs: .stand/logs/keeper.log, .stand/logs/desk.log
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAND="${ROOT}/.stand"
LOGS="${STAND}/logs"
[ -s "${STAND}/state.json" ] || { echo "Seed first: python3 scripts/seed.py" >&2; exit 1; }
mkdir -p "$LOGS"

running() {  # running NAME SCRIPT: true if the pid in .stand/NAME.pid runs SCRIPT
  [ -s "${STAND}/$1.pid" ] && ps -p "$(cat "${STAND}/$1.pid")" -o command= 2>/dev/null | grep -qF "$2"
}

start() {  # start NAME SCRIPT
  if running "$1" "$2"; then return; fi
  nohup python3 "$2" >> "${LOGS}/$1.log" 2>&1 &
  echo $! > "${STAND}/$1.pid"
  echo "started $1 (pid $!), log: ${LOGS}/$1.log"
}

stop() {  # stop NAME SCRIPT
  if running "$1" "$2"; then kill "$(cat "${STAND}/$1.pid")"; echo "stopped $1"; fi
  rm -f "${STAND}/$1.pid"
}

KEEPER="${ROOT}/agents/keeper/keeper.py"
DESK="${ROOT}/agents/desk/desk_stub.py"
claude_desk="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("desk", {}).get("managed", False))' "${STAND}/state.json")"

if [ "${1:-}" = "stop" ]; then
  stop keeper "$KEEPER"; stop desk "$DESK"; exit 0
fi

start keeper "$KEEPER"
if [ "$claude_desk" = "True" ]; then
  stop desk "$DESK"                       # the scripted desk from Tier A, if it is still running
  "${ROOT}/scripts/controller.sh" start   # desk itself is run by Switch's agent controller
else
  start desk "$DESK"
fi
sleep 4

set +e
python3 "${ROOT}/scripts/verify.py"; scenes=$?
echo; echo "Audit: Switch's approval record vs keeper's log"
python3 "${ROOT}/scripts/audit.py"; audit=$?
set -e
if [ "$scenes" -ne 0 ] || [ "$audit" -ne 0 ]; then
  echo "FAILED (scenes rc=$scenes, audit rc=$audit)"; exit 1
fi
echo "PASSED: every scene, and the record matches."
