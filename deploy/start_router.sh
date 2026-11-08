#!/bin/sh
set -eu

# Koyeb attaches the four tier volumes at /bs0db, /mc0db, /sc0db, and
# /gm0db. The router initializes their bootstrap tables and, only when all
# provider bindings are configured, signs the volume registry. Missing volume
# configuration is reported as unknown by /healthz instead of inventing health.
python -m runner_riddle.koyeb_bootstrap --write
exec python -m runner_riddle.http_service
