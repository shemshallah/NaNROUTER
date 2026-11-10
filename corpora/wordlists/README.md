# NaNROUTER wordlists / corpora

This directory is the canonical landing point for the wordlist bundle used by
NaNROUTER and the NaN* training pipelines.

Every source is published as its **own GitHub Release** with a stable
`wordlist-*` tag, so you can download only the list you want. The full combined
bundle is still available as `wordlists-latest`.

The payload is **not committed to git** because it is several gigabytes and
GitHub rejects individual files over 100 MB. The
[`Fetch wordlists`](../../.github/workflows/fetch-wordlists.yml) workflow runs on
a GitHub-hosted runner and publishes the archives as release assets.

## Pick one wordlist

Example: download SecLists only.

```sh
gh release download wordlist-seclists -R shemshallah/NaNROUTER
tar --zstd -xf seclists.tar.zst
```

Each release also contains a `<slug>.SHA256SUMS` file:

```sh
sha256sum -c seclists.SHA256SUMS
```

If a release is split into parts (larger lists), reassemble it:

```sh
cat seclists.tar.zst.part-* | tar --zstd -x
```

## Individual releases

| Release tag | Directory | Source |
|---|---|---|
| `wordlist-david47k-top-english-wordlists` | `david47k-top-english-wordlists` | <https://github.com/david47k/top-english-wordlists> |
| `wordlist-google-10000-english` | `google-10000-english` | <https://github.com/first20hours/google-10000-english> |
| `wordlist-dwyl-english-words` | `dwyl-english-words` | <https://github.com/dwyl/english-words> |
| `wordlist-en-wl-wordlist` | `en-wl-wordlist` | <https://github.com/en-wl/wordlist> (Aspell/SCOWL) |
| `wordlist-probable-wordlists` | `probable-wordlists` | <https://github.com/berzerk0/Probable-Wordlists> |
| `wordlist-wordset-dictionary` | `wordset-dictionary` | <https://github.com/wordset/wordset-dictionary> |
| `wordlist-neopass-wordlist` | `neopass-wordlist` | <https://github.com/neopass/wordlist> |
| `wordlist-scowl-mirror` | `scowl-mirror` | <https://github.com/rdeits/SCOWL-mirror> |
| `wordlist-nlile-dictionary-word-list` | `nlile-dictionary-word-list` | <https://github.com/nlile/dictionary-word-list> |
| `wordlist-frequencywords` | `frequencywords` | <https://github.com/hermitdave/FrequencyWords> |
| `wordlist-wikipedia-word-frequency` | `wikipedia-word-frequency` | <https://github.com/IlyaSemenov/wikipedia-word-frequency> |
| `wordlist-kkrypt0nn-wordlists` | `kkrypt0nn-wordlists` | <https://github.com/kkrypt0nn/wordlists> |
| `wordlist-wordfreq` | `wordfreq` | <https://github.com/rspeer/wordfreq> |
| `wordlist-seclists` | `SecLists` | <https://github.com/danielmiessler/SecLists> |
| `wordlist-scowl` | `scowl` | <https://downloads.sourceforge.net/wordlist/scowl-2020.12.07.tar.gz> |
| `wordlist-mit-wordlist-10000` | `mit-wordlist-10000` | <https://www.mit.edu/~ecprice/wordlist.10000> |
| `wordlist-crackstation-human-only` | `crackstation-human-only` | <https://crackstation.net/files/crackstation-human-only.txt.gz> |

## Full bundle

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

## Run the runner

```sh
gh workflow run fetch-wordlists.yml -R shemshallah/NaNROUTER
gh run watch -R shemshallah/NaNROUTER
```

Or use **Actions → Fetch wordlists → Run workflow** in the GitHub UI.

## Repo files

- `SOURCES.json` — sources and their release tags.
- `MANIFEST.json` — generated sizes, file counts, and release tags.
- `SHA256SUMS` — per-file checksums for the full bundle.
- `.gitignore` — keeps the multi-GB payload out of git.
