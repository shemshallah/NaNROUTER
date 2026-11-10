#!/bin/sh
set -eu

# Koyeb attaches the four tier volumes at /bs0db, /mc0db, /sc0db, and
# /gm0db. The router initializes their bootstrap tables and, only when all
# provider bindings are configured, signs the volume registry. Missing volume
# configuration is reported as unknown by /healthz instead of inventing health.
python -m runner_riddle.koyeb_bootstrap --write

# Optional persistent HW4 WordNet reference. The source ZIP is supplied by
# the operator on the NaNROUTER/MC0 volume, never by the BS0 learning ring.
# install() is digest-idempotent; a corrupt generation fails startup closed.
if [ -n "${RIDDLE_HW4_WORDNET_ZIP:-}" ]; then
    : "${RIDDLE_HW4_STORE:?Set dedicated HW4 persistent storage path}"
    case "$RIDDLE_HW4_STORE" in
        /bs0db|/bs0db/*) echo "HW4 cannot live on the BS0 main ring volume" >&2; exit 1 ;;
    esac
    python -m runner_riddle.hw4_full_dict install \
        "$RIDDLE_HW4_WORDNET_ZIP" "$RIDDLE_HW4_STORE"
    python -m runner_riddle.hw4_full_dict verify "$RIDDLE_HW4_STORE"
fi

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

exec python -m runner_riddle.http_service
