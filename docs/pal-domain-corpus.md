# PAL multi-domain Gutenberg corpus intake

The PAL language-model experiments use book-disjoint public-domain prose from [NaNROUTER corpora](../corpora/README.md). The current NaNROUTER Git tree holds metadata; **books are distributed as GitHub Release assets**, not committed files. This optional script prepares a new topical intake without modifying or uploading PAL model weights.

## Domains

Using Project Gutenberg `pg_catalog.csv` Subjects/LoCC metadata, the script labels whole books into medicine, science/technology, law/politics, economics/society, philosophy/religion, history/geography and literature. These are **subject buckets**, not a claim that the existing NaNROUTER releases are independently curated domain datasets.

## Running

On a machine with GitHub CLI, `zstd`, Python and network access:

```sh
mkdir -p downloads
gh release download corpora-paragraphs-0001 -R shemshallah/NaNROUTER \
  -p paragraphs-0001.tar.zst -p paragraphs-0001.SHA256SUMS -D downloads
(cd downloads && sha256sum -c paragraphs-0001.SHA256SUMS)
curl -fL 'https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv' \
  -o downloads/pg_catalog.csv

python scripts/build_pal_domain_corpus.py \
  --catalog downloads/pg_catalog.csv \
  --archive downloads/paragraphs-0001.tar.zst \
  --exclude-manifest path/to/PAL_R12/nanrouter/MANIFEST.json \
  --output pal-domain-corpus --max-per-domain 500
```

Repeat `--archive` for other releases: `corpora-paragraphs-0002` through `0010`. The default per-domain cap is chosen across the entire catalog, so **a single release batch may only contain part of the planned sample**. Read `corpora/paragraphs/BATCHES.json` for published book and byte counts.

Output is one `MANIFEST.json` with provenance and per-book SHA256, plus `train/<gutenberg-id>.txt`, `dev/<gutenberg-id>.txt`, and `test/<gutenberg-id>.txt`. It conforms to the PAL R11/R12 book loader's layout.

## Contamination and safety gates

- Split books before modeling and keep all works by the same author in one split. Exact duplicate book IDs, byte hashes and normalized-whitespace hashes are removed.
- Pass manifests from earlier PAL experiments to `--exclude-manifest` to avoid known historical books.
- **A completely sealed benchmark requires an additional all-lineage contamination and near-duplicate passage audit.** Domain selection alone does not guarantee independence.
- Sentences, paragraphs and short-stories derived from the *same Gutenberg book* do not count as three independent books. Prefer one canonical edition per Gutenberg ID.
- Keep wordlists (and especially credentials/password lists) out of primary next-token prose training. Public-domain Gutenberg books form the prose baseline.
- Inspect geographic copyright restrictions and Project Gutenberg license terms before redistribution.
- Store generated full corpora as release assets or an external data store; never check gigabytes into Git.

The companion PAL R12 CPU continuation is separately distributed with its single active checkpoint. The script in this pull request **does not train a model**; it makes new, audited input books available for later gated continuation.
