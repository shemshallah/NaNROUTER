# Router-owned NANNET/Koyeb portal image

**Live status:** the production Koyeb app `nannet` / service `nannet-portal`
now builds from **this repository** (`github.com/shemshallah/NaNROUTER`,
branch `main`, Dockerfile `deploy/portal/Dockerfile`). The prior
NaNLMind-owned deployment definition has been retired. The same persistent
`/data` volume, issuer database and Koyeb secrets were retained, so there is
one authority writer and no issuer fork.

The image pins NaNLMind commit `5667750539445b4c2ed7c26df702bfc7ae6ec1ec`,
builds the native logic checkpoint, and packages the existing portal,
CLOCKED gateway, head cortex and NANNET authority. It keeps **one public
port (8080)** with the workers on loopback. The root NaNROUTER `Dockerfile`
remains the independent BS0 runner control-plane image.

## Live cutover evidence

See [`docs/KOYEB_CUTOVER_EVIDENCE.md`](../../docs/KOYEB_CUTOVER_EVIDENCE.md).
The short version:

- Koyeb app `899d7db4-3273-4a8c-bc0c-eadb21833983` (`nannet`)
- service `00962492-a5ed-4788-bdc7-8d10257bfe1a` (`nannet-portal`)
- source `github.com/shemshallah/NaNROUTER`, `deploy/portal/Dockerfile`
- public host `https://nannet.apps.mistral.run`
- `/healthz`, `/portal` and `/v1/issuer` verified after cutover

## Deployment

1. Build `deploy/portal/Dockerfile` (CI: `.github/workflows/portal-image-ci.yml`).
2. Deploy as a web service on port `8080` with a persistent `/data` volume,
   the existing `NANLM_MERGE_TOKEN`, `NANNET_AUTHORITY_MASTER_KEY`, CLOCKED
   secrets and router HMAC/token secrets. Never commit any secret.
3. Verify `GET /healthz`, `GET /portal`, `GET /v1/issuer`, N16T, scoped
   pairing, `/v1/training/merge`, the `/v1/riddle/*` proxy,
   `/v1/head-cortex/*` and `/v1/rawroute/*`.
4. Keep exactly one service attached writable to the production `/data`
   volume. Use the previous deployment ID for rollback if a gate fails.

`deploy/portal/koyeb.yaml` remains a parameterized service definition for a
fresh/staging deployment. Do not point a second service at the production
`/data` volume while the live portal is writing.

## Router-owned Koyeb configuration examples

- `deploy/portal/koyeb.yaml` — parameterized staging service spec
- `deploy/portal/rawroute.koyeb.env.example` — non-secret mount/quota hints
- `deploy/portal/rawroute.mounts.koyeb.example.json` — example tier mount map

No secret, token, HMAC key, allocator manifest or live route cache belongs in
Git.
