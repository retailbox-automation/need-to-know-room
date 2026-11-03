#!/usr/bin/env bash
# Bring up a local Switch 0.31.0 stack (API, gateway, Mattermost) for Need-to-Know Room.
#
# The compose file and .env.example come straight from the Switch release tag,
# so nothing of Switch is copied into this repo. Secrets are generated locally
# into .stand/.env (mode 600) on the first run and reused after that.
#
#   ./scripts/up.sh            start (or restart) the stack
#   ./scripts/up.sh down       stop it, keep data
#   ./scripts/up.sh destroy    stop it and delete its volumes
#
# Ports default to 28000 (API), 23000 (gateway UI), 28065 (Mattermost) and
# 25432 (Postgres) so they rarely clash with anything already running.
# Override with N2K_API_PORT, N2K_GATEWAY_PORT, N2K_MM_PORT, N2K_PG_PORT.
set -euo pipefail

SWITCH_TAG="switch-v0.31.0"
SWITCH_VERSION="0.31.0"
RAW="https://raw.githubusercontent.com/sandbox-quantum/switch/${SWITCH_TAG}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAND="${ROOT}/.stand"
PROJECT="${N2K_PROJECT:-n2k}"
API_PORT="${N2K_API_PORT:-28000}"
GATEWAY_PORT="${N2K_GATEWAY_PORT:-23000}"
MM_PORT="${N2K_MM_PORT:-28065}"
PG_PORT="${N2K_PG_PORT:-25432}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required tool: $1" >&2; exit 1; }; }
need docker; need curl; need openssl; need python3
docker compose version >/dev/null 2>&1 || { echo "Docker Compose v2 is required (docker compose ...)." >&2; exit 1; }

compose() {
  docker compose -p "$PROJECT" --env-file "${STAND}/.env" -f "${STAND}/compose.yml" \
    --profile collab --profile gateway "$@"
}

# set_kv FILE KEY VALUE: replace KEY=... in FILE, or append it.
set_kv() {
  python3 -I - "$1" "$2" "$3" <<'PY'
import sys
path, key, value = sys.argv[1:4]
lines = open(path).read().splitlines()
out, done = [], False
for line in lines:
    if line.startswith(key + "="):
        out.append(f"{key}={value}"); done = True
    else:
        out.append(line)
if not done:
    out.append(f"{key}={value}")
open(path, "w").write("\n".join(out) + "\n")
PY
}

case "${1:-up}" in
  down)    compose down; exit 0 ;;
  destroy) compose down -v; exit 0 ;;
  up)      ;;
  *) echo "usage: $0 [up|down|destroy]" >&2; exit 2 ;;
esac

mkdir -p "$STAND"
chmod 700 "$STAND"
if [ ! -s "${STAND}/compose.yml" ]; then
  echo "Fetching the Switch compose file from tag ${SWITCH_TAG}"
  curl -fsSL "${RAW}/deploy/local/standalone-docker-compose.yml" -o "${STAND}/compose.yml"
fi

if [ ! -s "${STAND}/.env" ]; then
  echo "Writing ${STAND}/.env with fresh secrets"
  umask 077
  curl -fsSL "${RAW}/.env.example" -o "${STAND}/.env"
  # Same secrets as Switch's own `just init-env`, plus the two it leaves blank
  # that the agent controller needs (CONTROLLER_TOKEN_SECRET, the feature flag).
  for key in DB_PASSWORD DB_OWNER_PASSWORD AGENT_REGISTRATION_TOKEN GATEWAY_ADMIN_PASSWORD \
             MATTERMOST_ADMIN_PASSWORD MATTERMOST_USER_PASSWORD CONTROLLER_TOKEN_SECRET; do
    set_kv "${STAND}/.env" "$key" "$(openssl rand -hex 24)"
  done
  set_kv "${STAND}/.env" SECRET_KEYS "local:$(openssl rand -hex 32)"
  set_kv "${STAND}/.env" SWITCH_VERSION "$SWITCH_VERSION"
  # Agent management is a feature flag in 0.31.0; the old AGENT_MANAGEMENT_ENABLED
  # variable is refused at startup if set to true.
  set_kv "${STAND}/.env" FEATURE_FLAGS_ENABLED agent_management
  set_kv "${STAND}/.env" TELEMETRY_ENABLED false
  set_kv "${STAND}/.env" THIRD_PARTY_AVATARS_ENABLED false
fi
# Ports may change between runs; everything else in .env is kept.
set_kv "${STAND}/.env" API_HOST_PORT "$API_PORT"
set_kv "${STAND}/.env" GATEWAY_HOST_PORT "$GATEWAY_PORT"
set_kv "${STAND}/.env" MATTERMOST_HOST_PORT "$MM_PORT"
set_kv "${STAND}/.env" POSTGRES_HOST_PORT "$PG_PORT"
chmod 600 "${STAND}/.env"

compose pull --quiet
compose up -d

wait_for() {  # wait_for NAME URL SECONDS
  local i=0
  until curl -fs -o /dev/null "$2"; do
    i=$((i + 2))
    if [ "$i" -ge "$3" ]; then echo "$1 did not come up at $2 within $3 s" >&2; compose ps >&2; exit 1; fi
    sleep 2
  done
  echo "$1 is up: $2"
}
wait_for "Switch API" "http://127.0.0.1:${API_PORT}/health" 180
wait_for "Mattermost" "http://127.0.0.1:${MM_PORT}/api/v4/system/ping" 300
wait_for "Gateway UI" "http://127.0.0.1:${GATEWAY_PORT}/" 120

# The setup container seeds the Mattermost team, users and bridge; wait for it to finish.
i=0
while [ "$(docker inspect -f '{{.State.Status}}' "$(compose ps -a -q setup)" 2>/dev/null)" != "exited" ]; do
  i=$((i + 2)); [ "$i" -ge 240 ] && { echo "setup container did not finish in 240 s" >&2; exit 1; }
  sleep 2
done
code="$(docker inspect -f '{{.State.ExitCode}}' "$(compose ps -a -q setup)")"
[ "$code" = "0" ] || { echo "setup container exited with $code; see: docker compose -p $PROJECT logs setup" >&2; exit 1; }

cat <<EOF

Switch ${SWITCH_VERSION} is running.
  API          http://127.0.0.1:${API_PORT}
  Mattermost   http://127.0.0.1:${MM_PORT}
  Gateway UI   http://127.0.0.1:${GATEWAY_PORT}
Next: python3 scripts/seed.py
EOF
