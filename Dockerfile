FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RIDDLE_DATA_DIR=/data \
    PORT=8080

WORKDIR /app
COPY runner_riddle /app/runner_riddle

RUN useradd --system --uid 10001 --create-home riddle \
    && mkdir -p /data \
    && chown -R riddle:riddle /app /data

USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "runner_riddle.http_service"]
