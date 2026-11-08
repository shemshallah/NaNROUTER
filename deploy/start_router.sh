#!/bin/sh
set -eu

# Koyeb mounts the four tier volumes at these paths. The router owns the
# provider bindings and health registry, so initialize the tier databases and
# sign the registry before accepting runner heartbeats.
for tier in BS0 MC0 SC0 GM0; do
    case "$tier" in
        BS0) default_root="/0x7FF14E1100E8F17F" ;;
        MC0) default_root="/0x7FF14E1200D7F17F" ;;
        SC0) default_root="/0x7FF14E1300C2F17F" ;;
        GM0) default_root="/0x7FF14E1400A9F17F" ;;
    esac
    eval "configured_root=\${KOYEB_MOUNT_ROOT_${tier}:-}"
    root="${configured_root:-$default_root}"
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

# Opt-in verified native execution is activated only with explicit private
# portal delegation and receipt keys. The executable C core and NaN16 guests
# are image-built from a pinned NaN0S revision, never downloaded on startup.
if [ "${RIDDLE_HERMES_NATIVE_ENABLED:-0}" = "1" ]; then
    : "${RIDDLE_HERMES_DELEGATION_TOKEN:?HERMES portal delegation secret required}"
    : "${RIDDLE_HERMES_RECEIPT_HMAC_KEY:?HERMES receipt signing key required}"
    : "${RIDDLE_N16T_SUBMIT_TOKEN:?HERMES N16T guest submit secret required}"
    NAN16_LIBRARY=/app/native/libnan16.so
    HERMES_GUEST_IMAGE=/app/native/hermes.nan
    HERMES_GUEST_LABELS=/app/native/hermes.labels
    N16T_GUEST_IMAGE=/app/native/n16t.nan
    N16T_GUEST_LABELS=/app/native/n16t.labels
    RIDDLE_HERMES_NATIVE_LIBRARY_SHA256="$(cat /app/native/libnan16.sha256)"
    RIDDLE_HERMES_NATIVE_IMAGE_SHA256="$(cat /app/native/hermes.sha256)"
    test "$(sha256sum "$NAN16_LIBRARY" | cut -d' ' -f1)" = "$RIDDLE_HERMES_NATIVE_LIBRARY_SHA256"
    test "$(sha256sum "$HERMES_GUEST_IMAGE" | cut -d' ' -f1)" = "$RIDDLE_HERMES_NATIVE_IMAGE_SHA256"
    export NAN16_LIBRARY HERMES_GUEST_IMAGE HERMES_GUEST_LABELS
    export N16T_GUEST_IMAGE N16T_GUEST_LABELS
    export RIDDLE_HERMES_NATIVE_LIBRARY_SHA256 RIDDLE_HERMES_NATIVE_IMAGE_SHA256
fi

python -m runner_riddle.volume_registry --write

if [ "${RIDDLE_KOYEB_ROUTER_PORTAL_ENABLED:-0}" = "1" ]; then
    # NaNROUTER is the only public listener. Preserve the established
    # NANNET issuer key and SQLite database on the Koyeb persistent mount.
    : "${NANNET_AUTHORITY_MASTER_KEY:?preserve existing NANNET issuer key}"
    : "${NANLM_MERGE_TOKEN:?preserve existing merge authority key}"
    : "${RIDDLE_HERMES_DELEGATION_TOKEN:?router/portal private delegation key}"
    NANNET_AUTHORITY_DB="${NANNET_AUTHORITY_DB:-/data/nannet-authority.sqlite}"
    if [ "${RIDDLE_REQUIRE_EXISTING_ISSUER_DB:-0}" = "1" ] && [ ! -f "$NANNET_AUTHORITY_DB" ]; then
        echo "Refusing issuer replacement: existing NANNET pairing database not mounted" >&2
        exit 1
    fi
    NANNET_HERMES_ROUTER_URL="http://127.0.0.1:${PORT:-8080}"
    NANNET_HERMES_DELEGATION_TOKEN="$RIDDLE_HERMES_DELEGATION_TOKEN"
    RIDDLE_EMBEDDED_PORTAL_PORT=18085
    export NANNET_AUTHORITY_DB NANNET_HERMES_ROUTER_URL
    export NANNET_HERMES_DELEGATION_TOKEN RIDDLE_EMBEDDED_PORTAL_PORT
    # All non-router components are strictly private loopback workers.
    python /app/portal/training_merge.py --root /data --port 18085 --host 127.0.0.1 &
    portal_pid=$!
    PORT=18082 CLOCKED_GATEWAY_HOST=127.0.0.1 python -m nannet_clocked.gateway &
    clocked_pid=$!
    NANNET_AUTH_URL="http://127.0.0.1:18085" \
    NANLM_HEAD_CANDIDATE_DIR="${NANLM_HEAD_CANDIDATE_DIR:-/data/head-candidates}" \
        python /app/portal/head_cortex_service.py &
    head_pid=$!
    python -m runner_riddle.http_service &
    router_pid=$!
    trap 'kill "$router_pid" "$portal_pid" "$clocked_pid" "$head_pid" 2>/dev/null || true' EXIT INT TERM
    wait "$router_pid"
else
    exec python -m runner_riddle.http_service
fi
