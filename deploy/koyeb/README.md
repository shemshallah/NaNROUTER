# BS0:0 Koyeb service deployment

The Runner Riddle HTTP process is the persistent Bootstrap network/control node:

    nan://GM0:SC0:MC0:BS0:0:HW0:0

It is a control-plane companion to the existing NaNNet N16T/N16B bridge. It does not replace the bridge codec or claim to have been deployed automatically.

## Container

Build this repository's root `Dockerfile`. The process listens on `0.0.0.0:$PORT` (default 8080) and stores its SQLite inbox under `/data/runner-riddle.sqlite`.

## Required Koyeb configuration

- Web service port: `8080`
- Health check: `GET /healthz`
- Persistent volume: mount at `/data`
- Ensure the mounted directory is writable by container UID/GID `10001:10001`
- Set `RIDDLE_INTAKE_TOKEN` and `RIDDLE_WORKER_TOKEN` as separate random secrets, each at least 32 characters
- Set `RIDDLE_RANGE_HMAC_KEY` only after the canonical allocator issues a signed range manifest
- Set `RIDDLE_ROUTE_HMAC_KEY` to the independent key used to verify the signed master route cache
- Set `RIDDLE_FEEDBACK_HMAC_KEY` to an independent 32+ byte secret shared with Bootstrap for feedback verification
- Set `PORT=8080` and `RIDDLE_DATA_DIR=/data`
- Optional `RIDDLE_MAX_PENDING_EVENTS` defaults to 4096 and is capped at 65536

Do not commit any secret, token, HMAC key, allocator manifest, or live route cache to Git.

## API

- `GET /healthz`: public liveness, BS0:0 identity, queue counts, and range-manifest presence
- `POST /v1/riddle/intake`: intake-authenticated, bounded NaN source payload; stores source bytes with universe, node point, local head, source hash, ACL digest, and nanclock tick
- `POST /v1/riddle/lease`: worker-authenticated lease for one source event
- `POST /v1/riddle/ack`: worker ACK with trace/source provenance
- `POST /v1/riddle/retry`: release a failed lease or dead-letter after the attempt limit
- `GET /v1/riddle/queue`: worker-authenticated queue counts
- `POST /v1/riddle/feedback`: enqueue a provenance-bound candidate feedback envelope for Bootstrap MC0:0
- `GET /v1/riddle/feedback`: read pending feedback from the durable return queue
- `POST /v1/riddle/feedback/ack`: acknowledge feedback after Bootstrap ingests it
- `POST /v1/riddle/plan`: returns a bounded Boolean/routing job only when a signed allocator manifest is installed
- `POST /v1/riddle/routes/resolve`: resolves a typed address from the signed master cache and returns a signed micro-route packet; include `nanclock_tick` when selecting ephemeral heads; it never commits routes

Every POST requires JSON and an appropriate bearer token. Feedback envelopes are HMAC-signed with RIDDLE_FEEDBACK_HMAC_KEY before they enter the return queue. Request bodies are limited to 2 MiB. The durable source inbox defaults to 4096 queued/leased events and returns HTTP 429 when full. Intake payloads are hex-encoded NaN bytes.

## Important safety boundaries

- The service does not expose a live route-commit endpoint. Candidate feedback returns to Bootstrap through a separate durable queue and must be acknowledged after ingestion. The route resolver reads head and object association tables from the signed master cache; callers cannot supply substitute head maps.
- The macro planner writes only to candidate ranges and returns `live_map_commit=false`.
- Missing, invalid, unsigned, overlapping, or over-limit allocator ranges fail closed.
- Android range manifests are capped at 8 MiB; all manifests are capped at 2 GiB.
- Boolean learning is scheduled before routing; language demonstration remains blocked until its own bin and capability are granted.
- The service is not a 24/7 deployed listener until the image is built, attached to the persistent volume, configured with secrets, and health-checked in Koyeb.
