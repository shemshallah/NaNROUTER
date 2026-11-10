# HW5:0 Gutenberg — live NANNET/Koyeb C(256,2) corpus import

Status: **experimental, unmerged, and not deployed.** This branch stacks on
[NaNROUTER PR #115](https://github.com/shemshallah/NaNROUTER/pull/115),
which already published the pinned immutable Gutenberg generation in a GitHub
release. The diagnostic [PR #116](https://github.com/shemshallah/NaNROUTER/pull/116)
verified real HTTPS connectivity to the existing production Koyeb portal but
showed that protected ring endpoints return 401 without its private bearer.
**Neither that live probe nor this source branch proves a corpus was uploaded
to the production Koyeb volume.**

## Exact target and source

- Live transport: `https://nannet.apps.mistral.run/v1/ring/submit`
  behind the portal's existing `RUNNER_RING_TOKEN` authorization. No new
  issuer, network endpoint, or secondary service is created.
- Destination: **HW5:0**, the sole existing six-slot embedded runner-ring
  logical node. The active ring lease is required to import.
- Source: pinned, immutable [Gutenberg generation g1](https://github.com/shemshallah/NaNROUTER/releases/tag/hw5-gutenberg-c256-g1),
  archive SHA-256
  `906a9030a11a67cc2635a6700344826d4c924e49596e57949a969cf78e1a7a18`.
- Verified reference target: 20,597,424 normalized UTF-8 corpus bytes;
  8,388,608-byte C(256,2) root; 256 × 128-byte fixed heads,
  32,640 × 256-byte canonical pairs; exact ordered-triple SQLite ledger
  preserved separately. The projection is not a lossless replacement for
  all corpus bytes or its exact ordered triples.

## Existing NaNNet endpoint, real per-chunk acknowledgments

The one existing `POST /v1/ring/submit` route accepts a bounded envelope:

```json
{
  "frame": {
    "request_id": 0,
    "source_hw": 0,
    "destination_hw": 5,
    "nanclock_tick": 17,
    "kind": "hw5.gutenberg.c256.archive.v1",
    "acl_digest": "64-lowercase-hex-auth-context-digest",
    "word_hex": "8-byte-valid-Nan16DE-word-in-16-hex-characters"
  },
  "hw5_corpus": {
    "schema": "nanrouter.hw5-gutenberg-live-stream.v1",
    "archive_sha256": "906a9030a11a67cc2635a6700344826d4c924e49596e57949a969cf78e1a7a18",
    "operation": "begin",
    "size": 0
  }
}
```

The example illustrates fields only: `size=0` and placeholder frame strings
are deliberately **not** valid submission values. The client generates the
actual NaN16DE word and a positive pinned archive size. A begin frame has
request ID 0; sequential 128 KiB chunk frames use indices 1 onward with a
32-bit CRC of that chunk inside their NaN16DE word; seal uses request ID
`0xffffffff` and word payload `0xc2560001`. Every chunk has an independent
SHA-256, exact byte offset, and bounded base64 content. The full archive must
match the pinned SHA-256.

**Wire honesty:** an NPF1 point frame carries one exact NaN16DE word with a
32-bit payload. The bulk archive bytes travel in the *same authenticated
NANNET HTTPS request* as an explicitly typed opaque sidecar. They are not
pretended to fit in the 8-byte word, and the host driver does not implement a
new NaN opcode or train the learner. Only after the routed HW5:0 receiver
verifies every byte does it install the existing immutable NaN16 C256
projection plus exact-text/trigram sidecars.

The portal acknowledges a chunk only after fsyncing both the spool bytes and
the cursor. Replayed identical chunks are idempotent; altered or out-of-order
chunks are rejected. The cursor persists under the sole `/data` owner across
runner lease handoff. The final seal calls the original strict
`hw5_release_bootstrap.bootstrap` and rejects an archive or generated
artifact with an invalid digest. The immutable target never replaces an
existing divergent generation.

## What an authenticated live operator must do

1. Merge the base reference PR and this stacked integration after CI review.
2. Explicitly deploy the reviewed NaNROUTER portal image to the **existing**
   Koyeb `nannet-portal`, retaining its one /data volume and issuer.
   `no_deploy_on_push=true`: a GitHub merge alone does not deploy.
3. Confirm the portal reports `hw5_corpus_stream.configured=true` and
   `ring_endpoint=HW5:0` through authenticated `GET /v1/ring/status`.
4. Make a scoped `NANROUTER_RING_TOKEN` available only in a protected GitHub
   Actions environment. Existing diagnostic runs established that it is
   **not currently available** to the ordinary PR workflow.
5. Use the explicitly gated `hw5-live-c256-stream.yml` dispatch input
   `send_live=YES`, or execute
   `python3 tools/hw5_live_gutenberg_stream.py --send` from a privileged
   runner with the protected token in its environment.
6. Accept a live upload claim only if the final pinned archive receipt,
   C256 root digest, exact corpus digest, and a *separate remote*
   `GET /v1/ring/status` readback all match. Do not publish a successful
   result from merely posting frames or obtaining `delivered` transport ACKs.

The standard push CI tests the importer, integrity, replay, handoff and
preexisting portal resident behavior **offline**; the live transfer job
never runs automatically on a push. It fails closed without a protected
bearer and does not print secrets.

## Scientific boundaries

This transfers and seals an immutable corpus/reference object in the
existing logical HW5:0 ring. It does not claim that live Koyeb has accepted
the upload until the remote receipt is observed. It does not establish
native learner training, Gutenberg semantic acquisition, improved
cross-author generation, or a separate collective-mind instance.
Those require a subsequent guest-driven learner invocation and
independently heldout evaluation against the sealed root.
