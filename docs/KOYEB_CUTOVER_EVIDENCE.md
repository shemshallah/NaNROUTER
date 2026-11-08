# Koyeb cutover evidence — NaNLMind portal → NaNROUTER

Date: 2026-11-08 (UTC)
Operator action: live service source switched in place; volumes and secrets
retained.

## Final live binding

| Field | Value |
|---|---|
| Koyeb app | `nannet` — `899d7db4-3273-4a8c-bc0c-eadb21833983` |
| Koyeb service | `nannet-portal` — `00962492-a5ed-4788-bdc7-8d10257bfe1a` |
| Region | `was` |
| Public host | `https://nannet.apps.mistral.run` |
| Source repository | `github.com/shemshallah/NaNROUTER` |
| Branch | `main` |
| Dockerfile | `deploy/portal/Dockerfile` |
| Active deployment | `52e8dcfc-0c69-4e84-8826-7f97de3b6cc6` |
| Service version | `915` |
| Source commit built | `c15323d` (`fix/portal-ring-authority-copy-20261108`) |
| Pinned portal runtime | NaNLMind `431e0775cdb79b4cd59038a4ebe0df5434a17c92` |
| Status | `HEALTHY` |
| Auto-release group | `github.com/shemshallah/NaNROUTER` `refs/heads/main` |

The deployment definition after cutover:

```json
{
  "git": {
    "repository": "github.com/shemshallah/NaNROUTER",
    "branch": "main",
    "no_deploy_on_push": true,
    "docker": {"dockerfile": "deploy/portal/Dockerfile"}
  }
}
```

`no_deploy_on_push` is intentional: a source change must be deployed through a
reviewed rollout, never silently from a push.

## Atomic runner-ring authority

The same portal image now exposes the six-slot runner-ring authority:

```text
GET  /v1/runner-ring/clock
GET  /v1/runner-ring/status
GET  /v1/runner-ring/checkpoint
POST /v1/runner-ring/lease|renew|release|checkpoint
```

Authentication uses the Koyeb secret `nanrouter-runner-ring-token`
(`RUNNER_RING_TOKEN`, 32+ characters). The secret value is never stored in
Git. The first live `GET /v1/runner-ring/clock` returned
`nanclock_tick=1794169866474`.

### Single-service embedded ring (2026-11-08)

The extra `nanrouter-runner` Koyeb app/service created during testing was
deleted. The only Koyeb app is `nannet` and the only service is
`nannet-portal`. The portal now embeds one ring slot (`RUNNER_RING_EMBEDDED=1`,
slot `0`) and exposes the public ingress:

```text
https://nannet.apps.mistral.run/v1/ring/status
https://nannet.apps.mistral.run/v1/ring/points
https://nannet.apps.mistral.run/v1/ring/submit
https://nannet.apps.mistral.run/v1/ring/drain
https://nannet.apps.mistral.run/v1/ring/register
https://nannet.apps.mistral.run/v1/ring/checkpoint
https://nannet.apps.mistral.run/v1/ring/handoff
```

`NANROUTER_RUNNER_URL=https://nannet.apps.mistral.run` is the active embedded
endpoint. The embedded slot owns `HW5:0` while its lease is active and proxies
to an external active runner otherwise. Verified live:

```text
runner_ring_node.active = true
phase = active, slot = 0, epoch = 10
ring_endpoint = HW5:0
errors = 0
restart = restored active slot 0 from the persistent authority/checkpoint

GET  /v1/ring/points  -> HW0:0, HW2:0, HW5:0, HW9:0 active
POST /v1/ring/register {"hw":9} -> registered
POST /v1/ring/submit  HW0 -> HW9 -> delivered
POST /v1/ring/drain   {"hw":9} -> count 1, word 7ff112345678f8ff

HERMES in/out through the same public single-service ring:

POST /v1/ring/submit {HW2 -> HW5, kind=hermes.nan.out} -> delivered
POST /v1/ring/drain  {"hw":5} -> hermes.nan.out
POST /v1/ring/submit {HW5 -> HW2, kind=hermes.nan.in}  -> delivered
POST /v1/ring/drain  {"hw":2} -> hermes.nan.in
```

### External standby handoff evidence (2026-11-08)

The six identical non-Koyeb runner repositories were started against this
authority:

```text
slot 0  active   epoch 1  HW5:0   checkpoint d2fa6d5d...
slot 1  standby  epoch 1
slot 2  standby  epoch 1
slot 3  standby  epoch 1
slot 4  standby  epoch 1
slot 5  standby  epoch 1
```

Slot 0 was terminated. After the 30 s lease expired, slot 1 acquired:

```text
slot 1  active   epoch 2  HW5:0
checkpoint state_digest = d2fa6d5d306f15fce962096979d70ab9d6d7dc3cbd5d83e4e52ce4f71c02fc1d
portal active_slot = 1
portal handoffs = 2
```

The checkpoint digest is the same before and after handoff, so the bounded
HW5:0 fabric inbox was restored, not silently discarded. The runners do not
receive individual HW addresses; the ring as a whole is `HW5:0`.

## Preserved production state

The cutover changed the **same Koyeb service**, not a second service. This
keeps one writer on the production `/data` volume and one issuer authority.

| Resource | ID | Role |
|---|---|---|
| `/data` volume | `cc744aa3-a7b0-4c49-bdc8-1aa48fb5187f` | authority DB, training merge, rawroute, registry |
| `bs0db` volume | `169156ec-cf76-418d-a143-df904d5c7361` | BS0 tier |
| `mc0db` volume | `179ddf99-79d8-4780-a21b-11f98bf495b2` | MC0 tier |
| `sc0db` volume | `d8cd42fe-2c54-4f71-91d7-56ab84e3b684` | exists; SC0 root currently resolves under `/data` |
| `gm0db` volume | `14bc8408-1ab1-4a55-81af-dbffba18116c` | exists; GM0 root currently resolves under `/data` |

The `sc0db` and `gm0db` provider volumes are detached; their configured
mount roots (`/data/0x7FF14E13…`, `/data/0x7FF14E14…`) are directories on the
`/data` volume. This is reported honestly rather than promoted to green.

Koyeb secrets were not copied to Git and were not re-created. The portal reads
the same `NANNET_AUTHORITY_MASTER_KEY`, `NANLM_MERGE_TOKEN`, CLOCKED secrets,
and router HMAC/token secrets as before.

## Post-cutover verification

```text
GET https://nannet.apps.mistral.run/healthz  → 200
  nannet_authority = ready
  bsr_registered = 6
  nannet_bridge queued = 2
  rawroute namespaces = BS0, MC0, SC0, GM0
GET https://nannet.apps.mistral.run/v1/issuer → 200
  issuer_public_key = PrcSMYmuUIrXzqlpqdtnYPptSB2Yv6PuwF0WqWgICwA
GET https://nannet.apps.mistral.run/portal → 200
GET https://nannet.apps.mistral.run/v1/head-cortex/healthz → 200
GET https://nannet.apps.mistral.run/v1/rawroute/health → 401 (auth required)
```

The issuer public key is continuous with the pre-cutover authority database.
No second issuer was minted.

## Rollback

The previous NaNLMind-sourced deployment remains available:

| Field | Value |
|---|---|
| Rollback deployment | `f51a7c59-cc45-4117-93c6-f23ec27f5104` |
| Previous router-owned deployment | `9a12a2f0-51ad-4ce5-a4d7-6e7f222c8021` |
| Previous source | `github.com/shemshallah/NaNLMind` |
| Previous Dockerfile | `deploy/training_merge/Dockerfile` |

Rollback is a Koyeb deployment-image rollback (or a git-source PATCH back to
the previous definition). It must not replay stale leases or run two writers.
The persistent `/data` schema is forward-compatible; do not delete it.

## Repository retirement

NaNLMind PR #34 removed the old `deploy/training_merge/koyeb.yaml` source
manifest and documented the ownership transfer. It did **not** touch the live
Koyeb service. The live service is controlled by the binding above.

## Remaining operational gates

- Keep `NANNET_HERMES_ROUTER_URL` and `NANNET_HERMES_DELEGATION_TOKEN` unset
  until a verified private NaNROUTER HTTPS origin exists. The portal then
  delegates only scoped, signed `hermes:lease` requests.
- Keep one writable `/data` writer. Do not attach a staging service to the
  production volume.
- Verify DNS/TLS and the pinned issuer key before any hostname change.
- Record a new deployment ID here for every subsequent production rollout.
- Keep the runner-ring portal secret in Koyeb only; all six runners read the
  same `NANROUTER_RING_TOKEN` from their private environment.
