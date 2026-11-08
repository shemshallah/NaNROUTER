# NANNET portal ingress → NaNROUTER-owned HERMES lease universes

Status: **native NaN16DE lease and route consistency gates, router-side
durable HTTP lease delegation, and the live Koyeb source cutover are
implemented.** The production Koyeb service now builds from
`github.com/shemshallah/NaNROUTER` (`deploy/portal/Dockerfile`) while keeping
the same `/data` volume, issuer database, secrets and public hostname; see
`docs/KOYEB_CUTOVER_EVIDENCE.md`. The pre-cutover NaNLMind-sourced deployment
remains available for rollback.
**Native guest activation and N16T dispatch are implemented and verified in
CI when pinned NaN0S and N16T assets are configured.** Fail closed when no
authoritative route/lease context is supplied.

## Authority topology

```text
HERMES plugin (local NaN16DE universe)
  → HTTPS NANNET portal (pair/login, public address, issuer)
  → NaNROUTER (trusted lease ledger, signed route cache, node binding, NMP gate)
  → router-dispatched N16T/N16B traffic / native NaN16DE head execution
  ↔ NaNLMind ring and six ephemeral workers (canonical learner)
```

**Global endpoint** `nan://GM0:0::SC0:0::MC0:0::BS0:0::HW2:0` is the legacy HERMES
installation identity. It maps to the per-bootstrap node point **3**; the
number 3 is NOT a local head. A *distinct* per-lease universe identifier
resolves the leased universe, inside which head IDs 0–254 are addressable.
Position 255 is reserved for its one NANNET network port. The 255+1 ring
is local to each universe; independently leased universes are not merged
into the canonical NaNLMind learner.

Canonical router object roots use **the versioned grammar** in
`spec/address-grammar.md`, for example:

```text
nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW2:24:vector#1337
```

A textual route is a *requested path* only. It does not grant ownership.
The signed cache and authenticated, generation-bound lease determine the
actual target and capabilities. Never infer an object ID from raw memory
offsets. HERMES's older `nan://HW2:BS0:MC0:SC0:GM0` is a legacy *envelope*
coordinate order; it must be explicitly translated by a versioned endpoint
binding, never treated as a second authority.

## Existing service boundaries (verified from repositories)

Current NANNET portal is served from NaNLMind's Koyeb training-merge
deployment. Its code exposes `GET /v1/issuer`, `POST /v1/pair`,
`POST /v1/authorize`, and `POST /v1/nan16de/route`.
The HERMES plugin already supports Ed25519 installation pairing with
issuer-key pinning and a signed authorization check. Those endpoints are
**login/authorization**, not proof a separate HERMES universe was leased.
NANNET must not issue an executable universe based only on a caller's
requested address or successful login.

The currently committed NANNET authority default in
`NaNLMind/deploy/training_merge/start_portal.sh` is
`https://nannet.apps.mistral.run`. An alternate hostname, including
`nannet.app.mistral.com`, MUST be DNS/TLS/issuer-verified before
switching. Keep `NANNET_AUTH_URL` configurable and pin the issuer key,
not a bare domain name alone. Do not store bearer secrets in Git.

NaNROUTER already owns a distinct persistent service:
`Dockerfile`, `deploy/start_router.sh`, `runner_riddle/http_service.py`
and durable `/v1/riddle/*` routes. `/v1/nmp/lease` concerns
**NMP worker execution leases**, which are not equivalent to per-lease
HERMES universe allocation. **No current endpoint has been claimed
to issue the latter.**

## Native lease ABI

`mth/nan16/hermes_lease.nas`: native guest lifecycle:
`nhl_open`, `nhl_resolve`, `nhl_renew`, `nhl_release`.
The registry holds 16 simultaneous local lease slots, each with monotonically
increasing generation, lease ID, universe ID, owner tag, NANNET node point,
deadline tick, and status. This is a **bounded prototype**, not a production
global allocator. It does not provide durable persistence, an authenticated
source of ticks, or multi-process concurrency by itself.

`mth/nan16/hermes_nannet_route.nas`: guest route gate:
- r1 lease slot, r2 lease ID, r3 universe ID, r4 generation,
  r5 owner tag, r6 local head, r7 trusted tick, r8 **server-bound node point**.
- On success r1 universe, r2 local head, r3 0, r4 node point, r5 generation.
- Error r3 != 0 and output identity fields zeroed.
- Denies wrong owner, stale epoch, expired lease, already revoked lease,
  unauthorized node point (status 8), and network port as a learning head.

**Critical trust boundary:** all route-gate parameters tagged
`server-bound` or `trusted` MUST originate from the
portal-authenticated NaNROUTER context, NOT from an HTTP JSON body.
The opaque numeric `owner_tag` is only a consistency check inside the
NaN16 guest: it is **not cryptographic authorization**. Actual token,
installation-signature, route-ACL, and NMP admission verification remain
with their existing authoritative registry until natively implemented.
Neither the host nor the HERMES caller may fabricate a lease ID, universe
ID, generation, ticks, or NANNET node binding.

Native CI in `.github/workflows/hermes-native-nannet.yml` assembles
and runs the same NaN16 code with the canonical NaN0S VM.

## Required follow-on transaction before HERMES can use a remote lease

1. **Authenticated request:** HERMES pairs to NANNET using the pinned
   issuer and proves request ownership. Only independently authorized
   `universe:register` or equivalent scoped authority can request a
   remote lease; `training:execute` does not imply universe allocation.
2. **Router-owned allocation:** allocate a globally collision-safe
   `universe_id`, binding generation, node association and expiry in
   NaNROUTER's durable database with an atomic uniqueness constraint.
   Keep per-lease head namespace separate from the portal's permanent HW2.
3. **Signed lease receipt:** return lease metadata with a signed binding to
   installation identity, route root, node point, generation, scopes,
   expiry, and route-cache generation; replay and stale receipts rejected.
4. **NaN16 guest activation:** only after verification, load the receipt's
   trusted fields into `nhl_open`. Every head route checks the native
   `nhl_nannet_route` gate. Guest state snapshots are bound to the same
   generation; expiry/revocation blocks reuse.
5. **One traffic owner:** authenticated NANNET HTTPS ingress delegates
   opaque N16T/N16B packets and packet/lease context to NaNROUTER.
   Guest-owned N16T CRC, replay sequence and session transitions remain
   inside native NaN16. Never accept an arbitrary reverse-proxy URL.
6. **Independently gate learning:** remote HERMES output contributes only
   validated evidence/candidate deltas. The six CPU workers and canonical
   NaNLMind ring retain exclusive commit authority to their own topology.

## Koyeb ownership migration (performed 2026-11-08)

**Source deployment files to inventory and port:**
- `NaNLMind/deploy/training_merge/{Dockerfile,start_portal.sh,koyeb.yaml}`
- `NaNLMind/runner/training_merge.py` (currently provides portal and
  pairing-authority HTTP routes)
- `NaNLMind/nanlmind_nannet/` (issuer and N16DE/bridge codecs)
- `NaNLMind/runner/nannet_router/` (legacy embedded router)
- `NaNLMind/runner/nannet_clocked/` (Clocked gateway integration)
- `NaNLMind/runner/head_cortex_service.py` (read-only/candidate head work)

**Destination ownership:** `NaNROUTER/deploy/` and its authoritative
control-plane ingress; a distinct service/adapter still serves NaNLMind
training endpoints. Do not copy Python learning logic into native guest
execution: it belongs behind a bounded transport boundary. The project
requires future **NaN16DE-only guest logic**, while existing HTTPS/TLS,
issuer cryptography, and Koyeb volume setup remain non-guest infrastructure.

**Safe cutover sequence:**
1. Inventory exact Koyeb service/container revision, mount roots, database
   versions, signing-key location and public TLS hostname. Verify DNS
   ownership, Koyeb permissions and the pinned NANNET issuer fingerprint.
2. Add a router-side compatible **read-only shadow** of portal routes.
   Compare responses and permission denials without cloning private keys
   or accepting writes at two locations.
3. Stop old writers, make crash-consistent DB + volume backups, record SHA-256
   checksums, and restore to the target with restrictive permissions.
   Preserve token hashes, pairing codes, public identity bindings,
   revocations, generations, and the exact issuer key if continuity is
   intended. Do **not** mint a second issuer silently.
4. Start the new router deployment in private/staging mode; run signed
   pairing/authorization, device heartbeat, revocation, route, N16T,
   NMP lease/receipt, stale-generation, duplicate-ingest and rollback tests.
5. Move public ingress only after every fail-closed gate passes. Migrate
   one writer and one domain at a time; never run split-brain SQLite/lease
   authors. Keep old service **read-only** for rollback, not writable.
6. If any gate fails, stop new writes and restore previous routing against
   the same consistent DB generation. Never replay stale leases after rollback.

Secrets and Koyeb API credentials MUST be injected using private Koyeb secret
configuration, never source files, CI job logs or GitHub issues.

## Current code-level cross-repository handshake

The dedicated NaNROUTER POST `/v1/hermes/leases/open|resolve|renew|release`
endpoints are optional (disabled until both
`RIDDLE_HERMES_DELEGATION_TOKEN` and `RIDDLE_HERMES_RECEIPT_HMAC_KEY`
are supplied, each 32+ bytes). The delegated NANNET portal applies the separate
`hermes:lease` paired identity scope, Ed25519 method/path/body/timestamp/nonce
verification and private upstream secret before forwarding. The portal
sets HERMES's fixed HW2 node point 3 from server-owned routing context.

The SQLite authority persists per-installation 16-slot native generation
high-watermarks, independently random lease/universe IDs, recipient-bound
HMAC-signed receipts and revisions. The router rejects stale/altered/revoked
or expired receipts; the native guest separately rejects local head255
and mismatched generation/owner/point. Multiple HERMES universes MAY share
node point 3 without sharing a guest topology; node point alone is not a
unique universe identity.

The host router now optionally loads a SHA-256-pinned NaN0S guest image,
reconstructs per-installation native lease registries from authoritative
SQLite, calls actual `nhl_open`/`nhl_renew` and `nhl_nannet_route`, and
verifies VM output registers. It can dispatch opaque N16T work frames via
the existing N16T guest pool and journal at-most-once results. ACKs are
bound to signed live lease identity, head and response digest.
**This is real native guest route/protocol execution, not a canonical
NaNLMind model-training or knowledge-state commit.** The offline three-repo HTTP
handshake is exercised by `NaNLMind/integration/hermes_cross_repo_smoke.py`.
Production now uses the verified single-issuer Koyeb cutover recorded in
`docs/KOYEB_CUTOVER_EVIDENCE.md`; private runtime secrets remain in Koyeb.

## Runtime activation and staging image

The router Docker image builds two actual NaN16 guest images and the shared
C execution core from pinned NaN0S commit `fe636177027a1ede3f19939f7627e660e7bef5f3`.
On startup, `RIDDLE_HERMES_NATIVE_ENABLED=1` enables runtime only if
`RIDDLE_HERMES_DELEGATION_TOKEN`, `RIDDLE_HERMES_RECEIPT_HMAC_KEY`,
`RIDDLE_N16T_SUBMIT_TOKEN`, and standard router intake/worker/feedback
secrets are present. Read-only guest files and their build-time checksums
are checked before any lease is admitted. Staging service example:
`deploy/koyeb-hermes-staging.yaml`. The private portal must use the same
bearer as `NANNET_HERMES_DELEGATION_TOKEN` and a verified router **HTTPS**
origin in `NANNET_HERMES_ROUTER_URL`. Do not publish an unaudited public
HERMES router endpoint. Native restore rejects stale signed receipts and
rebuilds only live lease slots from the router SQLite ledger.

CI: `.github/workflows/hermes-native-runtime.yml` tests pinned native
lease activation, guest-owned N16T frame exchange, durable ACK, replay,
revocation, generation reuse and restart. `.github/workflows/hermes-deployment-image.yml`
checks that the deployable container actually includes native artifacts.

No change to NANNET's original public pairing issuer, DNS, external Koyeb
service or private storage has been made as part of this branch.

## HERMES N16T tenant isolation and dispatch recovery

The generic `/n16t` service and authenticated HERMES delegation **must not**
share the same native VM session pool. Their byte-for-byte N16T protocol frames
have only an opaque 16-byte session affinity key. NaNROUTER therefore operates
a **separate persistent native N16T guest pool for HERMES** at
`RIDDLE_HERMES_N16T_SESSION_STORE` (default
`/data/hermes-n16t-sessions.sqlite`). The regular `/n16t` pool retains
its own `RIDDLE_N16T_SESSION_STORE`. Startup refuses identical store paths.

The HERMES dispatch ledger atomically binds each opaque session ID to its
authenticated installation, lease ID, universe ID, native generation and
head 0..254. Two independent leased universes sharing physical HW2 point 3
cannot share a N16T guest session. The router checks this binding before
calling NaN16, leaving all CRC/sequence/packet semantics in the guest.

A router restart restores the accepted N16T guest session cursor from the
durable journal, rather than silently resetting it. The
`POST /v1/hermes/leases/inspect` delegated operation provides **read-only**
reconciliation by dispatch ID, installation, live receipt and head:
`not_recorded`, `pending_or_ambiguous`, `completed` or
`acknowledged`. A pending/ambiguous reservation is deliberately not retried;
operator intervention is required to distinguish crashes before/after guest
processing. Completed frames can be recovered by the original scoped caller;
a corrupt stored response is rejected even if its digest label was not changed.
This journal is not a canonical model-training history.

Keep all HERMES router SQLite files on a **persistent mounted volume**,
including the native N16T replay cursor and dispatch/session ownership journal.
Inspect is not callable with a revoked/expired lease; the NANNET portal verifies
the existing paired guest identity and scoped Ed25519 signature before
delegating. Avoid logging raw session IDs, guest frames or bearer tokens.
