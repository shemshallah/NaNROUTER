#!/bin/sh
set -eu

# The portal is the single public service. The runner-ring control plane runs
# on a loopback-only port inside the same container and is reached through the
# portal's /v1/riddle/* proxy.
for tier in BS0 MC0 SC0 GM0; do
    case "$tier" in
        BS0) fallback="/data/0x7FF14E1100E8F17F" ;;
        MC0) fallback="/data/0x7FF14E1200D7F17F" ;;
        SC0) fallback="/data/0x7FF14E1300C2F17F" ;;
        GM0) fallback="/data/0x7FF14E1400A9F17F" ;;
    esac
    eval "configured_root=\${KOYEB_MOUNT_ROOT_${tier}:-}"
    root="${configured_root:-$fallback}"
    mkdir -p "$root"
    db="$root/$(printf '%s' "$tier" | tr '[:upper:]' '[:lower:]')db.sqlite3"
    if [ ! -f "$db" ]; then
        python - "$db" "$tier" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS router_volume_bootstrap "
        "(tier TEXT PRIMARY KEY, created_at TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR REPLACE INTO router_volume_bootstrap(tier, created_at) "
        "VALUES (?, datetime('now'))",
        (sys.argv[2],),
    )
PY
    fi
done

# Optional HERMES outbound delegation is a separate private router service.
# Do not turn a missing upstream secret into a silent metadata-only fallback.
# The existing NANNET pairing DB remains the *only* public issuer/writer.
if [ -n "${NANNET_HERMES_ROUTER_URL:-}" ] || [ -n "${NANNET_HERMES_DELEGATION_TOKEN:-}" ]; then
    : "${NANNET_HERMES_ROUTER_URL:?verified private NaNROUTER URL required}"
    : "${NANNET_HERMES_DELEGATION_TOKEN:?private HERMES router bearer required}"
fi

# Write the signed registry even while tier volumes are being attached. The
# registry reports degraded mounts honestly; heartbeats still acknowledge the
# generation/digest and become green when the canonical mounts are present.
python -m nannet_router.volume_registry --write || test -f "${RIDDLE_VOLUME_REGISTRY_PATH:-/data/volume-registry.json}"

PORT=18081 python -m nannet_router.http_service &
router_pid=$!
PORT=18082 CLOCKED_GATEWAY_HOST=127.0.0.1 python -m nannet_clocked.gateway &
clocked_pid=$!
NANNET_AUTH_URL="${NANNET_AUTH_URL:-https://nannet.apps.mistral.run}" \
NANLM_HEAD_CANDIDATE_DIR="${NANLM_HEAD_CANDIDATE_DIR:-/data/head-candidates}" \
python /app/head_cortex_service.py &
head_pid=$!
trap 'kill "$router_pid" "$clocked_pid" "$head_pid" 2>/dev/null || true' EXIT INT TERM

exec python /app/training_merge.py --root /data --port 8080
