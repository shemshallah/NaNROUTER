# N16T HTTP worker handoff

Android's N16T transport posts the guest-built binary frame to `POST /n16t`
using `Content-Type: application/x-n16t`. This route is distinct from both
`/v1/point0` (N16B 64-bit-word envelopes) and the JSON NMP routes.

The wire frame is owned by the NaN16 guest:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 4 | ASCII `N16T` magic |
| 4 | 2 | version (little-endian; version 1) |
| 6 | 2 | message type (little-endian) |
| 8 | 16 | opaque session identifier |
| 24 | 4 | sequence number (little-endian) |
| 28 | 4 | payload length (little-endian) |
| 32 | N | payload |
| 32+N | 4 | CRC-32/IEEE (little-endian) |

The fixed header plus CRC is 36 bytes; the Android guest permits a maximum
payload of 65,536 bytes, so the transport frame limit is 65,572 bytes.

## Persistent NaN16 execution

`N16TGuestPool` loads the canonical NaN16 C execution core, a compiled
`n16t_android_guest.nas` image, and its assembler label map. Each active
128-bit session is assigned a persistent VM. The host uses the session bytes
only as an opaque VM-affinity key; CRC, replay, session ownership, message type,
logical routing, and state transitions are validated by the guest entry
`n16_server_exchange`.

The pool supports bounded concurrent sessions. Each VM serializes its own
state transitions; different sessions can execute in parallel. At capacity, the pool refuses new sessions rather than evicting a live
protocol state and erasing its replay cursor. A guest-validated CLOSE response
signals the pool to destroy that session VM and reclaim its slot.

Session VM state is persistent for the lifetime of the service process by
default. An optional durable SQLite store can checkpoint guest-validated
exchanges so a service restart restores the guest-owned session transitions and
replay cursors. Without a store, no database file is created and behavior is
exactly the original process-local model: clients must establish a fresh
session ID after reconnect.

The HTTP adapter passes the exact request bytes to this guest pool and returns
the exact guest-built response bytes.

## Durable session and replay checkpoints

`runner_riddle.n16t_guest.N16TSessionStore` is an optional SQLite-backed store.
Supply it directly, or pass a filesystem path and the pool opens and owns the
store:

```python
from runner_riddle import N16TGuestPool, N16THttpAdapter, WaveHttpServer
from runner_riddle.n16t_guest import N16TSessionStore

guest_pool = N16TGuestPool.from_env(max_sessions=8, store="n16t-sessions.sqlite3")
n16t = N16THttpAdapter(guest_pool.exchange)
server = WaveHttpServer(service, n16t_adapter=n16t)
try:
    server.start()
finally:
    server.stop()
    guest_pool.close()

# A caller-owned store is not closed by the pool and can be reopened after a
# process restart.
store = N16TSessionStore("n16t-sessions.sqlite3", max_sessions=8)
guest_pool = N16TGuestPool.from_env(max_sessions=8, store=store)
try:
    # Serve...
    pass
finally:
    guest_pool.close()
    store.close()
```

`from_env` also reads `RIDDLE_N16T_SESSION_STORE` (or the
`N16T_SESSION_STORE` alias) when no explicit store is supplied, so the primary
`python -m runner_riddle.http_service` entrypoint enables durable sessions
without code changes. The value is a filesystem path; `:memory:` is available
for tests but does not survive process exit.

The store is intentionally protocol-opaque. It persists only the 16-byte
session id, wire sequence indexes, and accepted request-frame bytes. The guest
remains the sole validator of CRC, message type, transition state, session
ownership, and replay sequencing. Schema version 1:

```sql
CREATE TABLE n16t_sessions (
    session_id BLOB PRIMARY KEY CHECK (length(session_id) = 16),
    cursor     INTEGER NOT NULL CHECK (cursor >= 0),
    state      BLOB NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE n16t_replay (
    session_id BLOB NOT NULL,
    sequence   INTEGER NOT NULL CHECK (sequence >= 0),
    frame      BLOB NOT NULL,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY (session_id) REFERENCES n16t_sessions(session_id)
        ON DELETE CASCADE
);
```

`state` is a versioned `N16S` checkpoint descriptor containing the replay
cursor and journal length. `n16t_replay` stores the actual accepted-frame
journal keyed by `(session_id, sequence)`. After every guest-validated,
successful exchange the pool commits a new journal row, cursor, descriptor, and
timestamp in one SQLite transaction before returning the response. The
primary key rejects a duplicate sequence with `N16TReplayError`; the pool never
advances a cursor for a frame the guest rejected.

A store adapter is any object exposing
`load_session(session_id) -> N16TSessionCheckpoint | None`,
`record_exchange(session_id, sequence, frame)`, and
`delete_session(session_id)`. A checkpoint carries the 16-byte session id, the
last guest-validated sequence (`cursor`), and the ordered opaque request frames.
The pool validates the checkpoint's session ownership and cursor consistency
before replaying it. A caller-supplied adapter is caller-owned and is not closed
by the pool; a store opened from a path is owned and closed by the pool.

On restart, the first frame for a session id makes the pool load that session's
journal, create a fresh VM, and replay the journal through the same
`n16_server_exchange` entry point. The guest reconstructs its own state and
replay cursor, so a replayed sequence and a session-ownership mismatch are
rejected by the same guest checks used by the in-memory path. The pool also
rejects a checkpoint whose session id does not match the frame's 16-byte key,
and a journal whose frame sequence is not strictly ordered, before serving any
new traffic. Passing a different session id selects a different stored session;
it cannot consume another session's cursor.

A guest-validated CLOSE removes the session and its complete journal instead of
journaling the terminal exchange. This preserves the in-memory rule that a
closed session releases its slot. `N16TSessionStore` supports bounded durable
capacity:

- `max_sessions`: maximum distinct durable sessions. A new session is refused
  when full; abandoned sessions are never silently evicted to admit another.
- `max_replay_frames`: maximum journal length for one session. Exceeding it
  fails closed rather than dropping replay history.
- `ttl_seconds` plus `cleanup_expired()`: whole-session expiry for abandoned
  sessions. The pool calls cleanup when it opens the store and before loading
  a session; active loaded sessions refresh `updated_at`. Administrative
  cleanup must not race a live runtime whose idle sessions are still wanted.

A pool path default uses the pool's `max_sessions` as the store bound. Pass a
configured `N16TSessionStore` when different store limits are required.

Durable checkpoints have deliberate limitations. Restore cost is proportional
to the replayed journal; the current guest has no raw VM state export/snapshot
ABI, so the accepted-frame journal is the checkpoint. Size the journal bound
and retention policy accordingly. A crash after the guest accepts an exchange
but before the SQLite transaction commits can lose that last cursor advance;
the response was not returned, so a client retry is at-least-once across that
window. Store I/O errors fail the exchange closed. The store assumes one
runtime writer at a time; it is not a multi-process coordination layer. Frames
are stored verbatim and the SQLite file is not encrypted, so do not place
bearer tokens or other credentials in N16T payloads, and protect the database
file with normal filesystem permissions. If no store is configured, none of
these files or behaviors are introduced.

## Runtime artifacts

Configure the runtime artifacts with:

- `NAN16_LIBRARY`: path to the shared library built from the NaN0S
  `aarch64/android/core` C sources.
- `N16T_GUEST_IMAGE`: `nan-text` image assembled from
  `src/nannet/n16t_android_guest.nas`.
- `N16T_GUEST_LABELS`: label map emitted by the same assembler invocation.

Example server wiring:

```python
from runner_riddle import N16TGuestPool, N16THttpAdapter, WaveHttpServer

guest_pool = N16TGuestPool.from_env(max_sessions=8)
n16t = N16THttpAdapter(guest_pool.exchange)
server = WaveHttpServer(service, n16t_adapter=n16t)
try:
    server.start()
    # Run the service's normal wait/shutdown loop here.
finally:
    server.stop()
    guest_pool.close()
```

The guest currently implements the server-side HELLO/CAPABILITIES handshake
and CLOSE response. CAPABILITIES carries logical portal point 1 in its first
two little-endian bytes; the remaining six bytes are reserved and zero. This
does **not** advertise corpus ingestion, training, candidate evaluation, or
merge capabilities. Other message types fail closed until their NaN16 guest
handlers and NMP worker handoff are implemented.

## Primary service deployment

The repository's primary `python -m runner_riddle.http_service` entrypoint also
mounts `POST /n16t` directly on `RiddleService`; it does not require the
separate `WaveHttpServer` test/embedded server. Enable the endpoint with:

- `RIDDLE_N16T_SUBMIT_TOKEN`: dedicated bearer credential, at least 32
  characters. This is separate from the intake and worker credentials.
- `RIDDLE_N16T_SESSION_STORE` (optional): SQLite path for durable N16T session
  and replay checkpoints. When absent, sessions remain process-local.
- `NAN16_LIBRARY`: shared library built from the canonical NaN0S C core.
- `N16T_GUEST_IMAGE`: compiled NaN16 guest image.
- `N16T_GUEST_LABELS`: label map emitted from the same image build.

When the N16T submit token is absent, the primary service returns 503 for
`/n16t` and does not allocate guest VMs. When the token is configured, startup
requires all three runtime artifacts; a partial or invalid runtime
configuration fails service startup rather than silently falling back.
The service closes the persistent guest pool during shutdown.

## HTTP security and protocol boundaries

The route requires the existing submit-role bearer token, rejects non-N16T
media types and out-of-range frames, disables request logging, and fails with
503 when no worker is configured. A guest failure or malformed response
returns a bounded 502. The callback receives no bearer token.

No host-side N16T parser, Python state machine, NMP JSON reinterpretation, or
point-0 N16B bridge is used for protocol decisions. The optional durable store
copies only the fixed session/sequence indexes and opaque frame bytes; the
guest still validates everything. The N16T guest runtime is now executable and
covered by a native-runtime CI job; the remote training worker and N16T-to-NMP
corpus/job handoff remain unfinished.
