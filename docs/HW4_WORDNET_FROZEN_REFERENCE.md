# Frozen HW4:0 WordNet reference — *offline* durable snapshot

This experimental facility preserves WordNet 3.1 in a reproducible, immutable
`C(256,2)`-addressed **reference**, so mathematical specialist universes can
be compared to one stable known mapping later. It is *not* a deployed HW4
NANNET service and must not be mounted over a live NaN16 guest universe.

## Format and ownership

One logical generation contains:

- `wordnet-c256.root` — exactly 8,388,608 bytes: 256 × 128-byte head slots
  plus 32,640 × 256-byte canonical mirror pair records.
- `wordnet-exact.sqlite3` — exact synset identities, lemma associations,
  glosses and typed directed relations, including head-hash collisions.
- `manifest.json` — SHA-256 of original `data.noun`, both snapshot files,
  source shape, mapping version, collision counts, and generation.
- `CURRENT.json` — one atomic pointer outside the generation directory,
  containing the manifest checksum and generation name.

The reference follows the existing NaNROUTER WordNet adapter's
`synset:<offset>-n` -> SHA-256 first big-endian u32 -> low-byte head
projection and canonical unordered pair indexing. The directional balance
projects to `pair lane0=f32 signed count`, `pair lane1=-lane0`. **This is a
lossy projection**, not a complete graph database. The external SQLite
table is essential: negative and positive edges may cancel in the root,
and distinct synsets may hash to one head. Exact concepts and typed edges
always survive in SQLite.

Head records contain offline count summaries and are not live ring-role
registers. In particular, real NANNET ingress and reserved hardware-node
heads have distinct namespaces and role policies: do not overwrite them
with these offline counts. A future HW4 service must provide authorized,
read-only API access to the verified generation and convert to native
guest ABI as appropriate.

## Publish and verify locally

```sh
python3 -m runner_riddle.hw4_reference install /path/to/data.noun \
  /var/lib/nanrouter/hw4-frozen-wordnet
python3 -m runner_riddle.hw4_reference verify \
  /var/lib/nanrouter/hw4-frozen-wordnet
python3 -m unittest tests.test_hw4_reference -v
```

The install takes one filesystem writer lock; builds in a private staging
directory; syncs artifacts; renames the completed generation; and **only
then** atomically advances the digest-pinned current pointer. Re-installing
identical source bytes returns the existing generation. A different source
digest increments the generation and retains earlier ones, never overwriting
them. The reader validates manifest digest, both file hashes, root size,
and exact overlay record counts. Protect the store with normal filesystem
permissions and keep snapshot backups; atomic rename alone cannot protect
against physical storage corruption.

GitHub Actions `.github/workflows/hw4-frozen-reference.yml` builds a
WordNet 3.1 reference from the Princeton database and uploads a reference
archive. **The archive is a CI artifact**, not proof of installation on
Koyeb, of successful NANNET routing, or of permanent public storage.

## Future specialist comparison

The NaNLM tensor experiment's five specialist files share the same:
- source corpus hash, WordNet version and event order;
- SHA-256 head coordinate projection;
- 32,640 unordered pair coordinate indexing.

But the *meaning* of lane 1 differs: the frozen WordNet reference uses
anti-symmetric reverse-sign evidence; the **experimental specialists**
place the previous temporal value of the same pair into their mirror
register. Do not compare mirror lanes as if they were equal quantities.
Compare separately named compatible scalar readings after an explicit
normalization and holdout protocol.

The future upper universe may **read** immutable, source-pinned reference
signatures as a control; it must never update the reference during decoder
training or treat a digest-mismatched matrix as ground truth.

The source package is Princeton WordNet 3.1. Preserve its full WordNet
license/copyright notice alongside any redistributed archive:
https://wordnet.princeton.edu/license-and-commercial-use
