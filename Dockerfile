# Source-pinned canonical NaN0S native VM and two independent NaN16 guests.
# Guest semantics are always executed in the NaN0S C core, never in Python.
FROM debian:bookworm-slim AS nan16-builder
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential ca-certificates gawk \
    && rm -rf /var/lib/apt/lists/*
ARG NAN0S_COMMIT=7f250a11bdb7845eae06ffb50df202187543ea5e
RUN mkdir -p /nan0s /out \
    && git -C /nan0s init \
    && git -C /nan0s remote add origin https://github.com/shemshallah/NaN0S.git \
    && git -C /nan0s fetch --depth 1 origin "$NAN0S_COMMIT" \
    && git -C /nan0s checkout --detach FETCH_HEAD \
    && test "$(git -C /nan0s rev-parse HEAD)" = "$NAN0S_COMMIT"
COPY mth/nan16/hermes_native_runtime.nas /src/hermes_native_runtime.nas
COPY mth/nan16/hermes_lease.nas /src/hermes_lease.nas
COPY mth/nan16/hermes_nannet_route.nas /src/hermes_nannet_route.nas
RUN set -eu; \
    cc -std=gnu99 -O2 -Wall -Wno-misleading-indentation \
       -ffp-contract=off -fno-fast-math -fPIC -shared -DNAN_WORDS=0x100000 \
       /nan0s/aarch64/android/core/nan16.c \
       /nan0s/aarch64/android/core/nan_dev.c \
       /nan0s/aarch64/android/core/nan_load.c \
       /nan0s/aarch64/android/core/nan_render.c \
       /nan0s/aarch64/android/core/nan_state.c \
       /nan0s/aarch64/android/core/nan_net_driver.c \
       -o /out/libnan16.so -lm; \
    cd /src; \
    awk -f /nan0s/tools/nmk.awk -v CMD=emit -v LABELS=/out/hermes.labels \
        hermes_native_runtime.nas > /out/hermes.nan; \
    awk -f /nan0s/tools/nmk.awk -v CMD=emit -v LABELS=/out/n16t.labels \
        /nan0s/src/nannet/n16t_android_guest.nas > /out/n16t.nan; \
    grep -q '^nhl_nannet_route ' /out/hermes.labels; \
    grep -q '^n16_server_exchange ' /out/n16t.labels; \
    sha256sum /out/libnan16.so | cut -d' ' -f1 > /out/libnan16.sha256; \
    sha256sum /out/hermes.nan | cut -d' ' -f1 > /out/hermes.sha256

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RIDDLE_DATA_DIR=/data \
    PORT=8080
WORKDIR /app
COPY runner_riddle /app/runner_riddle
COPY deploy/start_router.sh /app/start_router.sh
COPY --from=nan16-builder /out/ /app/native/
RUN useradd --system --uid 10001 --create-home riddle \
    && chmod 0755 /app/start_router.sh \
    && chmod -R 0555 /app/native \
    && mkdir -p /data /bs0db /mc0db /sc0db /gm0db \
    && chown -R riddle:riddle /app/runner_riddle /data /bs0db /mc0db /sc0db /gm0db
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/app/start_router.sh"]
