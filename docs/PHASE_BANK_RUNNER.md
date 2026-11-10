# Phase-bank runner

`runner_riddle/phase_bank_runner.py` schedules NaNLMind's raw-NaN16 phase
ingest. It does not compute vectors, trig, PQ, spectral or kNN values on the
host; it only stages command arguments, stores payloads, hashes artifacts and
publishes the manifest.

## Local validation

```sh
python3 -m runner_riddle.phase_bank_runner \
  --nanlmind /data/data/com.termux/files/home/NaNLMind \
  --corpus state/gutenberg_150_train.txt \
  --out-dir /data/data/com.termux/files/usr/tmp/phase_bank_smoke \
  --name smoke --dim 64 --window 8 --max-lines 1000 --max-windows 1000
```

## Release bank

Use chunked assets so no single file has to be retained locally:

```sh
python3 -m runner_riddle.phase_bank_runner \
  --nanlmind /data/data/com.termux/files/home/NaNLMind \
  --corpus state/gutenberg_150_clean_corpus.txt \
  --out-dir /data/data/com.termux/files/usr/tmp/phase_bank \
  --name gutenberg150_d64 --dim 64 --window 8 \
  --release --release-repo shemshallah/NaNLMind \
  --release-tag phase-bank-gutenberg150-d64-v1 \
  --chunk-bytes 188743680 --cleanup-local
```

`--chunk-bytes` writes an ordered `PREFIX.parts.json` plus `partNN` assets.
`--cleanup-local` deletes the bank, parts and sidecars only after all release
uploads succeed. The default output directory is under the approved termux
temporary directory, not `Download` and not either repository.

## Artifacts

The runner publishes the bank, codebook, PQ codes, residuals, sparse kNN,
spectral coordinates, vector-code matrix, triads and the runner manifest when
present. Each large asset is chunked below the configured limit; the parts
manifest carries the original SHA-256 and per-part hashes for reconstruction.
