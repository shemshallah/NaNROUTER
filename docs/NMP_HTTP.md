# NMP HTTP control plane

The NMP-aware routes are mounted by the existing WaveHttpServer when an
NmpHttpAdapter is supplied. They share the existing WaveService and WaveStore;
there is no parallel NMP database.

## Routes

| Method and path | Role | Purpose |
|---|---|---|
| POST /v1/nmp/packets | submit | Validate canonical packet and native receipt, run the server-side queue gate, and persist the queued packet inside the durable wave job payload |
| POST /v1/nmp/lease | worker | Acquire a durable worker lease, reconstruct the packet, and re-run start_execution() against that concrete lease |
| POST /v1/nmp/complete | worker | Recheck the executing packet against its job/lease binding and persist completion with the result digest |

All requests use the existing Authorization: Bearer roles and bounded JSON
framing from wave_http.py. Missing adapter configuration returns 503; it
never silently falls back to generic wave submission.

## Request shapes

Submit:

~~~json
{"packet": {"schema": "nanrouter.nmp.v1", "...": "canonical NmpPacket.to_dict()"}, "now_tick": 100}
~~~

Lease:

~~~json
{"owner": "worker-identity", "now_tick": 110, "lease_ticks": 64, "job_id": "nmp:..."}
~~~

Complete:

~~~json
{
  "packet": {"schema": "nanrouter.nmp.v1", "...": "packet returned by /lease"},
  "job_id": "nmp:...",
  "lease_token": "worker lease token",
  "lease_epoch": 1,
  "lease_owner": "worker-identity",
  "result_digest": "<sha256>",
  "now_tick": 120
}
~~~

## Required server wiring

Construct the adapter with the same WaveService instance used by the HTTP
server. The provided `WaveStoreNmpContextProvider` resolves the active operator
and native-verified runner capability from WaveStore; the admission, preflight,
ruleset, ring and cancellation snapshots remain explicit callbacks into the
authoritative server registries:

~~~python
from runner_riddle import (
    NmpHttpAdapter, WaveHttpServer, WaveStoreNmpContextProvider,
)

context = WaveStoreNmpContextProvider(
    service,
    admission_provider=current_admission,
    preflight_provider=current_preflight,
    ruleset_provider=current_ruleset_snapshot,
    ring_provider=current_ring_state,
    cancel_epoch_provider=current_cancel_epoch,
)
nmp = NmpHttpAdapter(service, context)
server = WaveHttpServer(service, host="127.0.0.1", port=8080, nmp_adapter=nmp)
server.start()
~~~

The provider requires an active operator record with native-verified evidence
and a matching dispatchable capability digest, workspace and precision. Its
`select_worker()` preflight runs the complete QUEUED-state gate for the chosen
runner before `lease_job()` writes a durable lease. A worker without the
matching native capability therefore cannot consume or strand a queued NMP
job. The adapter still rechecks the full gate against the concrete lease after
acquisition; if trusted evidence changes between the two checks, the lease
fails closed and expires back through the existing WaveStore lease lifecycle.

The context provider is a mandatory deployment dependency. It must not trust
client-supplied admission, capability, ruleset, ring or cancellation claims.
For the lease and complete stages it must return an expected_worker_owner
field derived from the native-verified capability registry; the adapter checks
that this value exactly matches the durable lease owner. A worker bearer token
alone is not a capability identity.
The adapter fails closed if the provider is absent or does not return a mapping.
The server still needs a TLS-terminating reverse proxy for non-loopback use.

## Security and evidence boundaries

- Submission requires a PREFLIGHTED packet, native_admission_required metadata,
  and a valid NaN16 guest receipt bound to that packet.
- The queue gate is evaluated using server-owned current evidence before the
  packet is persisted as a kind=nmp job.
- Worker leasing uses the worker role and the durable WaveStore lease.
  start_execution() re-evaluates the gate with the returned job and active
  lease; native packets also produce the receipt-to-lease binding.
- Completion requires an EXECUTING packet whose packet/job/lease identity
  agrees, then re-evaluates the native lease binding before complete_job().
- The result digest is evidence supplied by the worker; the adapter does not
  claim to independently recompute or certify the worker's output.
- Generic /v1/wave/jobs remains a generic job API and does not become an
  NMP admission shortcut.

The current adapter returns the canonical packet at each stage. NMP state is
reconstructed from the job payload plus the worker's returned execution packet;
the durable job/lease rows remain authoritative for queue and lease state.
