# NaNROUTER wordlists / corpora

This directory is the canonical landing point for the wordlist bundle used by
NaNROUTER and the NaN* training pipelines.

The bundle is **not committed to git** because it is several gigabytes and
GitHub rejects individual files over 100 MB. Instead, the
[`Fetch wordlists`](../../.github/workflows/fetch-wordlists.yml) workflow runs on
a GitHub-hosted runner, downloads every source into `corpora/wordlists/`, and
publishes the packed result as the **`wordlists-latest`** GitHub Release.

## Run the runner

```sh
gh workflow run fetch-wordlists.yml -R shemshallah/NaNROUTER
gh run watch -R shemshallah/NaNROUTER
```

Or use **Actions → Fetch wordlists → Run workflow** in the GitHub UI.

## Download the bundle

Release page:

<https://github.com/shemshallah/NaNROUTER/releases/tag/wordlists-latest>

The bundle is split into parts smaller than 2 GB. Reassemble and extract:

```sh
cat NaNROUTER-wordlists.tar.zst.part-* | tar --zstd -x
```

Verify the parts first:

```sh
sha256sum -c SHA256SUMS.parts
```

## What is included

| Directory | Source |
|---|---|
| `david47k-top-english-wordlists` | <https://github.com/david47k/top-english-wordlists> |
| `google-10000-english` | <https://github.com/first20hours/google-10000-english> |
| `dwyl-english-words` | <https://github.com/dwyl/english-words> |
| `en-wl-wordlist` | <https://github.com/en-wl/wordlist> (Aspell/SCOWL) |
| `probable-wordlists` | <https://github.com/berzerk0/Probable-Wordlists> |
| `wordset-dictionary` | <https://github.com/wordset/wordset-dictionary> |
| `neopass-wordlist` | <https://github.com/neopass/wordlist> |
| `scowl-mirror` | <https://github.com/rdeits/SCOWL-mirror> |
| `nlile-dictionary-word-list` | <https://github.com/nlile/dictionary-word-list> |
| `frequencywords` | <https://github.com/hermitdave/FrequencyWords> |
| `wikipedia-word-frequency` | <https://github.com/IlyaSemenov/wikipedia-word-frequency> |
| `kkrypt0nn-wordlists` | <https://github.com/kkrypt0nn/wordlists> |
| `wordfreq` | <https://github.com/rspeer/wordfreq> |
| `SecLists` | <https://github.com/danielmiessler/SecLists> |
| `scowl` | <https://downloads.sourceforge.net/wordlist/scowl-2020.12.07.tar.gz> |
| `crackstation-human-only.txt.gz` | <https://crackstation.net/files/crackstation-human-only.txt.gz> |
| `extras/mit-wordlist-10000.txt` | <https://www.mit.edu/~ecprice/wordlist.10000> |

`MANIFEST.json` records the generated sizes/file counts, and `SHA256SUMS`
contains per-file checksums for the extracted tree.
