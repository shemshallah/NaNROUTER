# Public-domain short stories

Short-story books and collections from the Project Gutenberg
**Category: Short Stories** bookshelf. Each `.txt` file is one Gutenberg
short-story book or collection, cleaned of the Gutenberg header/footer.

The full payload is published as the **`corpora-short-stories`** GitHub Release;
it is not committed to git because it is hundreds of megabytes.

## Download

```sh
gh release download corpora-short-stories -R shemshallah/NaNROUTER
tar --zstd -xf short_stories.tar.zst
```

If the release is split:

```sh
cat short_stories.tar.zst.part-* | tar --zstd -x
```

Each release also contains `short_stories.SHA256SUMS`.

## Source and license

- Source: [Project Gutenberg](https://www.gutenberg.org)
- Catalog: <https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv>
- The source eBooks are public domain in the United States.
- Project Gutenberg License: <https://www.gutenberg.org/policy/license.html>
- Some works may still be copyrighted outside the United States; check local law.

`SOURCES.jsonl` in the release lists every book used, with its Gutenberg ID,
title, author, source URL, and extracted sentence/paragraph counts.
