# Domain-diverse corpus

This directory indexes the domain-diverse training corpus. Unlike the
Gutenberg-derived categories, these collections deliberately cross genres:
encyclopedia, science, biomedicine, law, patents, code, mathematics,
journalism, cooking, cybersecurity, Q&A, multilingual text, finance,
standards, humanities, and chemistry.

**One collection = one public GitHub Release = one plain-text `.txt` file.**
There are no tar archives in these releases. Each `.txt` is UTF-8 with one
document per blank-line-separated block. Alongside the text, every release
contains:

| Asset | Purpose |
|---|---|
| `<collection>.txt` | The complete plain-text collection |
| `<collection>.SOURCES.json` | Source refs, licenses, files, document counts, and checksums |
| `<collection>.MANIFEST.json` | Machine-readable release metadata |
| `SHA256SUMS` | Checksum for the `.txt` |

The repository is public, so the releases and their assets are public. Use
`gh release list -R shemshallah/NaNROUTER` to see them.

## Collections

| Release tag | Domain | Main sources | License |
|---|---|---|---|
| `corpora-wikipedia-en` | Encyclopedia | English Wikipedia 2023-11-01 dump sample | CC BY-SA 4.0 |
| `corpora-arxiv` | STEM papers | arXiv metadata + abstracts (Cornell University snapshot) | CC0 1.0 |
| `corpora-pubmed` | Biomedicine | PubMed/PMC article + abstract pairs | CC0 1.0 |
| `corpora-law` | Law and government | U.S. Supreme Court opinions, Kentucky Revised Statutes | CC0 1.0 / Apache 2.0 |
| `corpora-patents` | Patents | US patent abstracts | Apache 2.0 |
| `corpora-code` | Programming | Codeforces submissions, Evol-Instruct code tasks | CC BY 4.0 / CC0 1.0 |
| `corpora-math` | Mathematics | Mathematics Stack Exchange | CC BY-SA 4.0 |
| `corpora-news` | News | CNN/Daily Mail articles, HuffPost headlines | CC0 1.0 / CC BY 4.0 |
| `corpora-recipes` | Cooking | Food.com recipes | CC0 1.0 |
| `corpora-security` | Cybersecurity | NVD CVE records, CISA KEV, EPSS | CC0 1.0 |
| `corpora-qa` | Q&A | Stack Exchange question/answer pairs | CC BY-SA 4.0 |
| `corpora-multilingual` | Multilingual | Wikipedia in French, German, Spanish, Russian, Arabic, Chinese, Hindi, and Swahili | CC BY-SA 4.0 |
| `corpora-finance` | Finance | SEC EDGAR 10-K narrative sections | CC0 1.0 |
| `corpora-standards` | Technical standards | IETF RFC series | IETF Trust |
| `corpora-humanities` | Religion and poetry | Public-domain spiritual texts, Gutenberg poetry | CC0 1.0 |
| `corpora-chemistry` | Chemistry | Chemistry problem/solution pairs | CC0 1.0 |

Caps are intentionally below the 2 GiB GitHub release-asset limit. The default
caps live in [`scripts/build_diverse_corpus.py`](../../scripts/build_diverse_corpus.py)
and can be overridden per run. A collection is a sample, not a claim that the
entire upstream source was downloaded.

## Download

One collection:

```sh
gh release download corpora-arxiv -R shemshallah/NaNROUTER
sha256sum -c SHA256SUMS
```

All collections (this does not fetch the large assets):

```sh
gh release list -R shemshallah/NaNROUTER --limit 100 | grep '^Corpus:'
```

The metadata index is the `corpora-domains-latest` release:

```sh
gh release download corpora-domains-latest -R shemshallah/NaNROUTER
```

## Rebuild

The workflow is
[`Fetch diverse corpus`](../../.github/workflows/fetch-diverse-corpus.yml). It
runs one GitHub Actions runner per collection and publishes each release as
soon as that collection is built.

```sh
gh workflow run fetch-diverse-corpus.yml -R shemshallah/NaNROUTER \
  -f collections=all -f max_mb=0 -f publish=true
gh run watch -R shemshallah/NaNROUTER
```

Build a subset or a smaller probe:

```sh
gh workflow run fetch-diverse-corpus.yml -R shemshallah/NaNROUTER \
  -f collections=arxiv,pubmed,standards -f max_mb=0 -f publish=true

gh workflow run fetch-diverse-corpus.yml -R shemshallah/NaNROUTER \
  -f collections=chemistry -f max_mb=5 -f publish=false
```

## Kaggle secret

Kaggle sources need an API token. The workflow reads the repository secret
`KAGGLE_API_TOKEN`; set it once from a Kaggle `KGAT_...` token or from
`~/.kaggle/kaggle.json`:

```sh
gh secret set KAGGLE_API_TOKEN -R shemshallah/NaNROUTER < ~/.kaggle/access_token
```

The token is only used by the runner to download public Kaggle datasets. It is
never written to a release or committed to the repository.

## Provenance and licenses

Each release's `SOURCES.json` records the upstream dataset reference, URL,
license, license URL, files used, and document/byte counts. The collections mix
licenses; check `SOURCES.json` before redistributing a derivative. In
particular:

- Wikipedia text is CC BY-SA 4.0 and requires attribution/share-alike.
- Stack Exchange and Mathematics Stack Exchange text is CC BY-SA 4.0.
- arXiv metadata is CC0; the abstracts remain the work of their authors.
- PubMed/PMC text is distributed under the upstream open-access terms.
- IETF RFC text is reproduced under the IETF Trust legal provisions.
- Codeforces submissions are CC BY 4.0 at the dataset level; source code
  remains the work of its authors.

NaNROUTER does not claim ownership of the source text. The releases are
training-data mirrors with machine-readable provenance, not a relicense.

## Layout of a `.txt`

```
Title: Example article
Categories: cs.CL

Abstract: This is the first document. Paragraphs are separated by a blank
line, so a document boundary is exactly one blank line.

Title: Another article
...
```

The builder writes a trailing newline. It never inserts a header or footer, so
the file can be consumed by the existing byte/BPE corpus tooling without
special-casing.
