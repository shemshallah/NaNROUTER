# nanlmv3 corpus

## 100M corpus

```text
path:   nanlmv3/data/corpus_100m.txt
bytes:  100,000,001
files:  256 books
sha256: 232f3edcd2294dd65f758e82d0bdb90c0e5bee3c8f9dc7942ffcedd1be4b0f1c
```

It is built from the published `corpora-sentences-0001` release (377 MB of
Gutenberg sentences), with Project Gutenberg START/END boilerplate removed.
The data directory is gitignored; regenerate it with:

```sh
gh release download corpora-sentences-0001 -R shemshallah/NaNROUTER \
  --pattern 'sentences-0001.*' --dir build/release
(cd build/release && sha256sum -c sentences-0001.SHA256SUMS)
tar --zstd -xf build/release/sentences-0001.tar.zst -C build/corpus

python nanlmv3/prepare_corpus.py \
  --source build/corpus \
  --bytes 100000000 \
  --output nanlmv3/data/corpus_100m.txt \
  --manifest nanlmv3/data/corpus_100m.json
```

## Chunk-disjoint training sample

Taking `head -c` from the filename-sorted corpus creates an out-of-distribution
validation split. `sample_corpus.py` instead samples contiguous chunks evenly
across the corpus, reserves interleaved chunks for validation, and writes them
last:

```sh
python nanlmv3/sample_corpus.py \
  --source nanlmv3/data/corpus_100m.txt \
  --output build/model_sample.txt \
  --bytes 20000000 --chunks 20 --val-chunks 2 \
  --manifest build/model_sample.json
```

This gives 18 training chunks and 2 held-out chunks, with the held-out chunks
at roughly 31.3 MB and 67.7 MB in the source.

## Multi-domain corpus

The Gutenberg-only 100M corpus is still a useful staged baseline, but it is no
longer the only option. The `corpora-domains-latest` release indexes 16 public
domain collections published as one plain-text file per release:

| Domain | Release |
|---|---|
| Encyclopedia | `corpora-wikipedia-en` |
| STEM papers | `corpora-arxiv` |
| Biomedicine | `corpora-pubmed` |
| Law | `corpora-law` |
| Patents | `corpora-patents` |
| Code | `corpora-code` |
| Mathematics | `corpora-math` |
| News | `corpora-news` |
| Cooking | `corpora-recipes` |
| Cybersecurity | `corpora-security` |
| Q&A | `corpora-qa` |
| Multilingual | `corpora-multilingual` |
| Finance | `corpora-finance` |
| Technical standards | `corpora-standards` |
| Humanities | `corpora-humanities` |
| Chemistry | `corpora-chemistry` |

```sh
gh release download corpora-domains-latest -R shemshallah/NaNROUTER
gh release download corpora-wikipedia-en -R shemshallah/NaNROUTER
gh release download corpora-arxiv -R shemshallah/NaNROUTER
```

Each release contains `<collection>.txt`, `<collection>.SOURCES.json`, and
`SHA256SUMS`. The source/license manifest is in
[`corpora/domains/README.md`](../corpora/domains/README.md). A domain mix should
be assembled from these releases with an explicit provenance file rather than
silently concatenating every collection; the current builder caps each
collection well below the 2 GiB release-asset limit.
