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
server and a trusted context provider:

~~~python
from runner_riddle import NmpHttpAdapter, WaveHttpServer

def current_nmp_context(*, packet, stage, job, lease):
    # Read current admission, preflight, ruleset snapshot, capability,
    # ring incarnation/epoch and cancellation state from server-owned stores.
    # Return the keyword arguments accepted by NmpPacket.queue() or
    # NmpPacket.start_execution()/execution_gate(). Raise if evidence is absent.
    return load_current_gate_evidence(packet, stage, job, lease)

def verify_worker_identity(token, owner):
    # Resolve the presented worker credential to its server-issued principal,
    # then require that principal to own the requested native capability.
    # Compare a token hash or opaque credential ID; never log or persist token text.
    return worker_registry.verify_owner(token, owner)

nmp = NmpHttpAdapter(service, current_nmp_context, verify_worker_identity)
server = WaveHttpServer(service, host="127.0.0.1", port=8080, nmp_adapter=nmp)
server.start()
~~~

The context provider and worker identity provider are mandatory deployment dependencies. The
context provider must also return `expected_program_id` from the server-owned function
registry at queue, lease, and completion stages; this independently binds the guest-echoed
program ID to the function/capability mapping instead of trusting a host-supplied receipt word.
worker identity provider must bind the presented worker credential to the requested
capability owner before the durable lease is acquired, and must recheck that binding
against the durable lease owner at completion. A worker role token alone is not a
worker identity. It should compare an opaque credential identifier or token hash and
must never log or persist bearer-token text. The context provider must not trust
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
