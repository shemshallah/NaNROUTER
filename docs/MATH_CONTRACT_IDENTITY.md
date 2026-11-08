# Math contract identity (A-54)

**Status:** implemented locally; code + tests are in this revision.
**Scope:** `runner_riddle/math_objects.py`, `runner_riddle/nmp.py`,
`runner_riddle/math_linker.py`.

A-54 adds an optional function-contract digest to candidate and NMP operation
identity. The binding is fail-closed when a digest is supplied and a contract is
available to recompute it, but it does **not** change any legacy identity when
the field is absent.

## Candidate identity

`MathCandidate` has an optional `contract_digest` field (64 lowercase hex
characters). `candidate_id_for()` accepts the matching optional keyword:

```python
candidate_id_for(snapshot_id, inputs, function_id, function_version,
                 contract_digest=None)
```

* When `contract_digest` is omitted, the digest payload is exactly the legacy
  payload: `snapshot_id`, `inputs`, `function_id`, `function_version`. Existing
  `cnd:` identifiers therefore stay stable.
* When it is supplied, the canonical payload gains `contract_digest`, so the
  candidate identity changes.
* `MathCandidate.to_dict()` includes `contract_digest` only when it is not
  `None`. Legacy candidate serialization is unchanged and old stored payloads
  still load. The candidate schema remains `nanrouter.math-candidate.v1`.

## Linker contract computation

`math_linker.py` no longer treats a caller-supplied `contract_digest` as
authoritative:

* A `MathFunction` is digested with its own `MathFunction.digest()` method,
  which excludes the declared `contract_digest` field.
* A mapping/object contract is rebuilt into the canonical function-contract
  document (`schema`, function id/version, signature, semantics,
  pre/post/undefined conditions, numerical policy, implementations, proof
  status, lifecycle status) and digested.
* If the caller supplied `contract_digest`, it must equal the recomputed value.
  A mismatch raises `LinkError` with code `contract_digest_mismatch`.
* Generated `MathCandidate` records carry the recomputed digest, and their
  `candidate_id` is derived with that digest. `LinkSnapshot.function_digests`
  and `LinkResult.functions` already expose the same digest for evidence.

For a canonical `MathFunction`, the linker digest equals
`MathFunction.digest()`, so the linker, registry, and store agree on one
contract identity.

## NMP operation identity

`NmpPacket` has an optional `function_contract_digest` field.
`dedupe_key_for()` and its `dedupe_key()` alias accept
`function_contract_digest=None`.

* When absent, the dedupe payload is byte-for-byte the legacy operation key:
  no new key is added.
* When present, `function_contract_digest` is normalized to bare lowercase hex
  and added to the dedupe payload. Two packets that differ only by contract
  digest therefore have different dedupe keys, packet IDs, and operation IDs.
* `NmpPacket.to_dict()` adds `function_contract_digest` only when set.
  `NmpPacket.from_dict()` accepts both new and old records; old records rebuild
  with `None`. Packet serialization of legacy packets is unchanged.
* `nmp.prepare()` copies `candidate.contract_digest` into the packet, so linker
  candidates automatically produce contract-bound NMP operations. A legacy
  candidate (no digest) still produces the legacy packet and key.
* Malformed non-`None` digests are rejected by `MathCandidate`,
  `candidate_id_for()`, `dedupe_key_for()`, and `NmpPacket`.

## Test evidence

`python3 -m unittest tests.test_math_objects tests.test_nmp tests.test_math_linker -q`

Covered cases:

* legacy candidate IDs, legacy packet dedupe keys, and legacy serialization
  remain unchanged when the optional digest is omitted;
* supplying a contract digest changes candidate IDs, NMP dedupe keys, packet
  IDs, and operation IDs;
* linker recomputes the digest and rejects tampered supplied values for both
  mappings and `MathFunction` objects;
* candidate and packet serialization roundtrip with and without the field;
* one-sided compatibility: legacy candidates/packets stay legacy, while
  digest-bound candidates prepared into packets keep the binding and do not
  deduplicate against legacy operations.

## Limitations

* NMP can bind the digest it is given, but a packet contains no full function
  contract, so NMP cannot independently recompute the contract digest. The
  linker is the recomputation boundary; callers that bypass it remain
  responsible for supplying the true digest.
* A digest-bound candidate and a legacy candidate with the same content use
  different identities by design. They must not be treated as duplicates until
  one side is migrated.
* `math_validity._candidate_from_mapping()` currently reconstructs only the
  legacy candidate fields, so a mapping roundtrip through that helper drops
  `contract_digest`. The helper was outside this change's ownership. Direct
  `MathCandidate` objects and the linker path retain the field.
* The digest is a content identity, not authority, proof, admission, or a
  signature. It does not make a candidate executable.
