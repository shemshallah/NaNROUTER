# Public-domain short stories

Short-story books and collections from the Project Gutenberg
**Category: Short Stories** bookshelf. Each `.txt` file is one Gutenberg
short-story book or collection, cleaned of the Gutenberg header/footer.

Files are grouped into batches of up to 1,000 books, and **each batch is its
own GitHub Release**, so you can download only the slice you want.

## Choosable releases

| Release | Contents |
|---|---|
| `corpora-short-stories` | Complete corpus |
| `corpora-short-stories-0001`, `-0002`, ... | One batch of up to 1,000 books each |

`BATCHES.json` in this directory maps every batch tag to its book count, file
count, and compressed size. To make smaller releases, run the workflow with a
lower `batch_size` input (for example `250`).

Download one batch:

```sh
gh release download corpora-short-stories-0001 -R shemshallah/NaNROUTER
tar --zstd -xf short_stories-0001.tar.zst
```

Download the complete corpus:

```sh
gh release download corpora-short-stories -R shemshallah/NaNROUTER
tar --zstd -xf short_stories.tar.zst
```

If an archive is split into parts:

```sh
cat short_stories.tar.zst.part-* | tar --zstd -x
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

`SOURCES.jsonl` lists every book used, with its Gutenberg ID, title, author,
source URL, and extracted sentence/paragraph counts.
