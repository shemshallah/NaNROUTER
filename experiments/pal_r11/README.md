# PAL R11 — NaNROUTER-only corpus connector

This is a **corpus importer**, NOT a second model or a trained replacement.
It consumes release assets published under `shemshallah/NaNROUTER/corpora/*`;
GitHub does not commit those large `.tar.zst` files in its git tree.

The CI smoke gate downloads `corpora-short-stories-0001`, verifies the
release asset's SHA-256 digest, and exports exact UTF-8 text per whole book.
Book split assignment is stable across categories and batches by Gutenberg ID:
90% train / 5% dev / 5% test. Duplicated source IDs and byte-identical books
are discarded. The list of earlier HW5 IDs known to NaNROUTER is excluded.

**Caution:** This is not proven fully independent of the entire historical R10
training set, because the R10 source archive does not list every Gutenberg ID.
A truly blind test requires checking all original source IDs first.

To import multiple local verified release archives without sampling:
```bash
python3 experiments/pal_r11/import_nanrouter_corpora.py \
  --archive path/to/short_stories-0001.tar.zst \
  --archive path/to/paragraphs-0002.tar.zst \
  --out output/raw_books
```
For a small sample, add `--max-bytes-per-split 2000000`.
Every document is kept separately, so the PAL trainer must reset/document-mask
at book boundaries rather than treating concatenated unrelated books as prose.

**One active checkpoint:** This step does not edit `r10_active.pal10`.
The existing PAL R10/R11 weights, stream optimizer and temporal rails must be
resumed by the same model trainer once verified data are available. No separate
checkpoint, vocabulary, or independent model is created here.
