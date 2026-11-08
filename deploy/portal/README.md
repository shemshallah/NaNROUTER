# Router-owned NANNET/Koyeb portal image

This is the migration target for the currently NaNLMind-owned Koyeb training-merge portal. The existing NaNROUTER root `Dockerfile` remains the independent BS0 runner control-plane image. The new `deploy/portal/Dockerfile` pulls **exactly** NaNLMind commit `5667750539445b4c2ed7c26df702bfc7ae6ec1ec`, compiles native logic training, and packages the same portal modules, CLOCKED gateway, head cortex and NANNET authority. The portal retains **one public port**, with the workers on loopback, and retains the existing /data schema and credentials.

Deployment stages:
1. Merge this image only after `portal-image-ci` builds and imports successfully.
2. Deploy `deploy/portal/koyeb.yaml` as a **separate staging service** with new staging secrets and staging /data. Do not point it at the production issuer database or attach the live production volume while the old service is writing.
3. Verify `GET /healthz`, `GET /portal`, N16T, scoped pairing, `/v1/training/merge`, and the BS0 proxy and CLOCKED/head-cortex routes; inspect audit and idempotency behavior. A successful Docker build alone does not verify these end-to-end behaviors.
4. Back up the production persistent volume and document writer quiescence. Only after staging parity is confirmed, cut over the **same production /data volume with exactly one active writer**. Preserve Koyeb secrets in Koyeb, never in Git.
5. Confirm the old and new health responses, device lease and training generation, with no replay or split-brain writers. Roll back the image (not the persistent schema) if any checks fail.
6. In a follow-up NaNLMind PR **after live cutover confirmation**, remove the old `deploy/training_merge/` deployment files and `config/rawroute.*koyeb*` examples. Do not delete the live deployment in advance.

No live deployment, secret update, data migration, or removal has been performed by adding this image.

## Router-owned Koyeb configuration examples

The staging rawroute mount configuration examples now live in NaNROUTER,
alongside the actual router-owned deployment artifact:

- `deploy/portal/koyeb.yaml` — staging service spec, not a production cutover
- `deploy/portal/rawroute.koyeb.env.example` — non-secret mount/quota hints
- `deploy/portal/rawroute.mounts.koyeb.example.json` — example tier mount map

**Ownership is not live deployment**: verify the exact Koyeb data mount and
issuer key before enabling or replacing the production service. Do not
delete NaNLMind's legacy live-runtime source while Koyeb may still build it;
NaNROUTER's portal Docker image is source pinned to a NaNLMind commit.
