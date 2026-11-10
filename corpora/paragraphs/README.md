# Public-domain paragraphs

One paragraph per line, derived from Project Gutenberg English texts.

Each source book is a separate `.txt` file named
`<gutenberg-id>--<author>--<title>.txt`. Files are grouped into batches of up to
1,000 books, and **each batch is its own GitHub Release**, so you can download
only the slice you want.

## Choosable releases

| Release | Contents |
|---|---|
| `corpora-paragraphs` | Complete corpus |
| `corpora-paragraphs-0001`, `-0002`, ... | One batch of up to 1,000 books each |

`BATCHES.json` in this directory maps every batch tag to its book count, file
count, and compressed size. To make smaller releases, run the workflow with a
lower `batch_size` input (for example `250`).

Download one batch:

```sh
gh release download corpora-paragraphs-0001 -R shemshallah/NaNROUTER
tar --zstd -xf paragraphs-0001.tar.zst
```

Download the complete corpus:

```sh
gh release download corpora-paragraphs -R shemshallah/NaNROUTER
tar --zstd -xf paragraphs.tar.zst
```

If an archive is split into parts:

```sh
cat paragraphs.tar.zst.part-* | tar --zstd -x
```

Every release contains a matching `SHA256SUMS` file. The complete archive also
contains the root metadata; each batch archive contains only that batch's
`.txt` files and `SOURCES.jsonl`.

## Source and license

- Source: [Project Gutenberg](https://www.gutenberg.org)
- Catalog: <https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv>
- The source eBooks are public domain in the United States.
- Project Gutenberg License: <https://www.gutenberg.org/policy/license.html>
- Some works may still be copyrighted outside the United States; check local law.

The selection and counts are recorded in `MANIFEST.json` after each runner run.
`SOURCES.jsonl` lists every book used, with its Gutenberg ID, title, author,
source URL, and extracted sentence/paragraph counts.
