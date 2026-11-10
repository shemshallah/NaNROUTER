# Public-domain sentences

One sentence per line, derived from Project Gutenberg English texts.

The full payload is published as the **`corpora-sentences`** GitHub Release; it
is not committed to git because it is hundreds of megabytes.

## Download

```sh
gh release download corpora-sentences -R shemshallah/NaNROUTER
tar --zstd -xf sentences.tar.zst
```

If the release is split:

```sh
cat sentences.tar.zst.part-* | tar --zstd -x
```

Each release also contains `sentences.SHA256SUMS`.

## Source and license

- Source: [Project Gutenberg](https://www.gutenberg.org)
- Catalog: <https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv>
- The source eBooks are public domain in the United States.
- Project Gutenberg License: <https://www.gutenberg.org/policy/license.html>
- Some works may still be copyrighted outside the United States; check local law.

The selection and counts are recorded in `MANIFEST.json` after each runner run.
`SOURCES.jsonl` in the release lists every book used, with its Gutenberg ID,
title, author, source URL, and extracted sentence/paragraph counts.
