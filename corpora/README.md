# NaNROUTER corpora

Large corpora are published as GitHub Releases, not committed to git. Each
category has a stable release tag and a manifest in this tree.

| Category | Release tag | Contents |
|---|---|---|
| [`wordlists/`](wordlists/README.md) | `wordlists-latest` + `wordlist-*` | Wordlists, frequency lists, SecLists, SCOWL, and related sources |
| [`sentences/`](sentences/README.md) | `corpora-sentences` + `corpora-sentences-*` | One sentence per line, one file per Gutenberg book, in choosable batches |
| [`paragraphs/`](paragraphs/README.md) | `corpora-paragraphs` + `corpora-paragraphs-*` | One paragraph per line, one file per Gutenberg book, in choosable batches |
| [`short_stories/`](short_stories/README.md) | `corpora-short-stories` + `corpora-short-stories-*` | Project Gutenberg short-story books and collections, in choosable batches |
| [`domains/`](domains/README.md) | `corpora-<domain>` + `corpora-domains-latest` | Domain-diverse text: enwiki, arXiv, PubMed, law, patents, code, math, news, recipes, security, Q&A, multilingual, finance, standards, humanities, chemistry. One `.txt` per collection |

## Public-domain pipeline

The public-domain categories are built by
[`Fetch public domain corpus`](../.github/workflows/fetch-public-domain-corpus.yml)
using [`scripts/build_public_domain_corpus.py`](../scripts/build_public_domain_corpus.py).

```sh
gh workflow run fetch-public-domain-corpus.yml -R shemshallah/NaNROUTER
gh run watch -R shemshallah/NaNROUTER
```

Defaults: up to **10,000 English Gutenberg books**, including every available
English book in the **Category: Short Stories** bookshelf. The bookshelf has
4,128 books across all languages; the current catalog contains **3,615 English**
short-story books, all of which are included.

Each public-domain category is published twice: as a complete release and as
choosable batch releases of up to **1,000 books** each (for example
`corpora-sentences-0001`). Every batch contains individual per-book `.txt`
files, so you can download only the slice you need. The batch mapping is in
`BATCHES.json` inside each category.

## Source and license

Project Gutenberg: <https://www.gutenberg.org>

The source eBooks are public domain in the United States. Some works may still
be copyrighted outside the United States. Project Gutenberg License:
<https://www.gutenberg.org/policy/license.html>.
