# WikiText-103

[WikiText-103](https://blog.einstein.ai/the-wikitext-long-term-dependency-language-modeling-dataset/)
is a 103M-token English language-modeling corpus extracted from the set of
verified Good and Featured Wikipedia articles. It retains original case,
punctuation, and numbers, and is split into train, validation, and test sets.

This directory holds the release metadata. The corpus payload itself is **not
committed to git** because it is over 1 GB. The
[`Fetch WikiText-103`](../../.github/workflows/fetch-wikitext103.yml) workflow
runs on a GitHub-hosted runner, verifies the official archives, and publishes
the splits as GitHub Releases.

## Releases

| Release tag | Variant | Contents |
|---|---|---|
| `wikitext103` | Raw | `wiki.train.raw`, `wiki.valid.raw`, `wiki.test.raw` |
| `wikitext103-tokenized` | Tokenized | `wiki.train.tokens`, `wiki.valid.tokens`, `wiki.test.tokens` |
| `wikitext103-latest` | Index | Combined `MANIFEST.json`, `SOURCES.json`, and `SHA256SUMS` |

The raw variant preserves the original text before unknown-token replacement.
The tokenized variant is the word-level release in which out-of-vocabulary
tokens have been replaced with `<unk>`.

## Splits

Each file is UTF-8 text with one line per source line, including blank lines.
`Words` is the number of whitespace-separated tokens.

| Variant | Split | File | Bytes | Lines | Words |
|---|---|---|---:|---:|---:|
| Raw | train | `wiki.train.raw` | 540,568,191 | 1,801,350 | 101,425,671 |
| Raw | validation | `wiki.valid.raw` | 1,146,846 | 3,760 | 213,886 |
| Raw | test | `wiki.test.raw` | 1,290,590 | 4,358 | 241,211 |
| Raw | **total** | | **543,005,627** | **1,809,468** | **101,880,768** |
| Tokenized | train | `wiki.train.tokens` | 539,209,157 | 1,801,350 | 101,425,671 |
| Tokenized | validation | `wiki.valid.tokens` | 1,142,309 | 3,760 | 213,886 |
| Tokenized | test | `wiki.test.tokens` | 1,281,077 | 4,358 | 241,211 |
| Tokenized | **total** | | **541,632,543** | **1,809,468** | **101,880,768** |

Combined payload: **1,084,638,170 bytes** across both variants.

## Download

Download the raw variant:

```sh
gh release download wikitext103 -R shemshallah/NaNROUTER
sha256sum -c SHA256SUMS
```

Download the tokenized variant:

```sh
gh release download wikitext103-tokenized -R shemshallah/NaNROUTER
sha256sum -c SHA256SUMS
```

Each release contains its own `MANIFEST.json`, `SOURCES.json`,
`SHA256SUMS`, and `LICENSE.txt`. The `wikitext103-latest` release contains the
combined index and checksums for both variants.

## Run the runner

```sh
gh workflow run fetch-wikitext103.yml -R shemshallah/NaNROUTER
gh run watch -R shemshallah/NaNROUTER
```

The workflow:

1. Downloads `wikitext-103-raw-v1.zip` and `wikitext-103-v1.zip` from the
   official WikiText host.
2. Verifies the archives and every extracted split against published
   SHA-1/SHA-256 checksums and expected sizes.
3. Publishes `wikitext103`, `wikitext103-tokenized`, and `wikitext103-latest`.
4. Commits the generated `MANIFEST.json`, `SOURCES.json`, and `SHA256SUMS`
   back to this directory.

To build the payload locally without publishing:

```sh
python3 scripts/build_wikitext103.py \
  --output-dir build/corpora/wikitext103 \
  --work-dir /tmp/nanrouter-wikitext103
```

## Source and license

- Dataset: WikiText-103 (v1), Salesforce AI Research
- Homepage: <https://blog.einstein.ai/the-wikitext-long-term-dependency-language-modeling-dataset/>
- Paper: [Pointer Sentinel Mixture Models](https://arxiv.org/abs/1609.07843)
- Raw archive: <https://wikitext.smerity.com/wikitext-103-raw-v1.zip>
- Tokenized archive: <https://wikitext.smerity.com/wikitext-103-v1.zip>
- License: [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) and GFDL

WikiText-103 is derived from Wikipedia. Retain the attribution and license
notice when redistributing the corpus or derived works. See `LICENSE.txt`.

## Citation

```bibtex
@misc{merity2016pointer,
  title={Pointer Sentinel Mixture Models},
  author={Stephen Merity and Caiming Xiong and James Bradbury and Richard Socher},
  year={2016},
  eprint={1609.07843},
  archivePrefix={arXiv},
  primaryClass={cs.CL}
}
```
