# Native NaN16 preflight receipts

## Purpose

`NativePreflightReceipt` binds a successful NaN16 guest decision to one
immutable NMP packet. It is a control-plane identity/evidence record. The
module hashes metadata and descriptors only; it does not evaluate mathematics,
compute an operator result, verify a theorem, or attest that a guest actually
ran.

## Receipt binding

A valid receipt binds:

- packet and candidate IDs;
- snapshot ID, base generation, and input generation;
- function ID/version and canonical input-operand digest;
- ruleset snapshot ID, rule epoch, and all 256 bits of the rule digest;
- canonical capability-set digest and capability epoch;
- expected output generation and complete output-descriptor digest;
- pinned guest source and image digests; and
- zero guest status / VALID result.

The only creation path accepts a normalized guest result with status zero,
exactly eight rule-digest words, and the complete eight-word output descriptor.
A denied guest result cannot produce a receipt. `NmpPacket.mark_preflight`
requires a matching VALID admission record and attaches the receipt to packet
evidence. The NMP execution gate revalidates it against the packet on every
queue/lease gate evaluation.

## Worker lease binding

After queueing, `NmpPacket.bind_native_lease` binds the receipt to one active
job lease and ring snapshot. The binding includes job ID, lease epoch, owner,
a digest of the lease token (never the token itself), ring incarnation/epoch,
output generation, and cancellation epoch. The active slot/alias and JAHS
handoff seal must match.

The NMP execution gate also requires the live ruleset snapshot to expose the
same rule epoch and complete 256-bit digest. Native-receipt packets force a
fresh full gate evaluation at queue and lease start; a previously accepted
decision cannot be replayed after the live ruleset, capability, or ring
snapshot changes. At lease start, NMP recomputes the binding from the current
job, lease token, and ring snapshot and compares it to the stored binding.
`start_execution` refuses a packet with a native receipt unless that exact
binding is present and unchanged.

## Evidence boundary

These hashes are content-binding digests, not signatures. A caller that can
forge the normalized guest result can also forge the receipt. Production
attestation still needs a trusted guest image/source measurement and a
transport/host boundary that cannot manufacture guest results. The receipt
does not itself replace ACL authorization, capability verification, ring
lifecycle checks, or the MthSystem/WaveService durable lease path. P5.f remains
responsible for making the NMP packet/receipt/lease the mandatory route to
point-0 execution and immutable result commit.
