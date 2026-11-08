FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RIDDLE_DATA_DIR=/data \
    PORT=8080

WORKDIR /app
COPY runner_riddle /app/runner_riddle
COPY deploy/start_router.sh /app/start_router.sh

RUN useradd --system --uid 10001 --create-home riddle \
    && chmod 0755 /app/start_router.sh \
    && mkdir -p /data /bs0db /mc0db /sc0db /gm0db \
    && chown -R riddle:riddle /app /data /bs0db /mc0db /sc0db /gm0db

USER 10001:10001
EXPOSE 8080
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()"]
ENTRYPOINT ["/app/start_router.sh"]
