# NaNROUTER owns the Koyeb portal deployment. Pinned upstream runtime inputs.
# This is separate from the BS0 runner-riddle container; no duplicated state owner.
FROM debian:bookworm-slim AS native
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ARG NANLMIND_COMMIT=5667750539445b4c2ed7c26df702bfc7ae6ec1ec
RUN mkdir -p /src && git -C /src init \
 && git -C /src remote add origin https://github.com/shemshallah/NaNLMind.git \
 && git -C /src fetch --depth 1 origin "$NANLMIND_COMMIT" \
 && git -C /src checkout --detach FETCH_HEAD \
 && test "$(git -C /src rev-parse HEAD)" = "$NANLMIND_COMMIT" \
 && make -C /src -j2 \
 && mkdir -p /state \
 && /src/build/nanlm-universal logic-train 8 16 /state/hermes-universe.nmg

FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir cryptography 'clocked-sdk==0.7.0'
COPY --from=native /src/runner/training_merge.py /app/training_merge.py
COPY --from=native /src/runner/hermes_router_delegate.py /app/runner/hermes_router_delegate.py
COPY --from=native /src/runner/head_cortex_service.py /app/head_cortex_service.py
COPY --from=native /src/runner/nannet_router /app/nannet_router
COPY --from=native /src/runner/nannet_clocked /app/nannet_clocked
COPY --from=native /src/nanlmind_nannet /app/nanlmind_nannet
COPY --from=native /src/build/nanlm-universal /app/nanlm-universal
COPY --from=native /state/hermes-universe.nmg /app/state/hermes-universe.nmg
COPY deploy/portal/start_portal.sh /app/start_portal.sh
ENV PYTHONUNBUFFERED=1 \
    NANLM_NATIVE_BINARY=/app/nanlm-universal \
    NANLM_HEAD_STATE=/app/state/hermes-universe.nmg \
    NANLM_HEAD_CORTEX_HOST=127.0.0.1 \
    NANLM_HEAD_CORTEX_PORT=18083 \
    NANLM_HEAD_CANDIDATE_DIR=/data/head-candidates
VOLUME ["/data"]
EXPOSE 8080
RUN chmod 0755 /app/start_portal.sh /app/nanlm-universal \
 && chmod 0644 /app/state/hermes-universe.nmg
CMD ["/app/start_portal.sh"]
