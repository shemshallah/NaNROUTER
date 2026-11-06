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

python -m runner_riddle.volume_registry --write
exec python -m runner_riddle.http_service
