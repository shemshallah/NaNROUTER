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
exec python -m runner_riddle.http_service
