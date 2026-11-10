# NaNROUTER corpora

Large corpora are published as GitHub Releases, not committed to git. Each
category has a stable release tag and a manifest in this tree.

| Category | Release tag | Contents |
|---|---|---|
| [`wordlists/`](wordlists/README.md) | `wordlists-latest` + `wordlist-*` | Wordlists, frequency lists, SecLists, SCOWL, and related sources |
| [`sentences/`](sentences/README.md) | `corpora-sentences` | One sentence per line, derived from Project Gutenberg |
| [`paragraphs/`](paragraphs/README.md) | `corpora-paragraphs` | One paragraph per line, derived from Project Gutenberg |
| [`short_stories/`](short_stories/README.md) | `corpora-short-stories` | Project Gutenberg short-story books and collections |

## Public-domain pipeline

The public-domain categories are built by
[`Fetch public domain corpus`](../.github/workflows/fetch-public-domain-corpus.yml)
using [`scripts/build_public_domain_corpus.py`](../scripts/build_public_domain_corpus.py).

```sh
gh workflow run fetch-public-domain-corpus.yml -R shemshallah/NaNROUTER
gh run watch -R shemshallah/NaNROUTER
```

Defaults: up to **10,000 English Gutenberg books**, including all available
English books in the **Category: Short Stories** bookshelf (currently 4,128).

## Source and license

Project Gutenberg: <https://www.gutenberg.org>

The source eBooks are public domain in the United States. Some works may still
be copyrighted outside the United States. Project Gutenberg License:
<https://www.gutenberg.org/policy/license.html>.
