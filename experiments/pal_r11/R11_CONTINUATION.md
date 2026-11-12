# PAL R11 — unified raw-prose continuation

This experiment continues the **single** PAL R10 streaming-subword checkpoint. It is separate from NaNLMind and Poincaré R27/R28.

## Corpus intake

The R11 workflow `.github/workflows/pal-r11-nanrouter-corpus.yml` successfully downloaded, SHA-256 verified, and extracted NaNROUTER release `corpora-short-stories-0001`. Its artifact `pal-r11-nanrouter-raw-prose-books` contains whole-book, document-disjoint raw UTF-8 (with punctuation, case, newlines, whitespace). The 6 MB export includes 12 train books, 12 development books, and 14 test books; the source manifest records Gutenberg identifiers and SHA-256 digests. Training uses only `shemshallah/NaNROUTER/corpora/*`.

## Single-checkpoint model

The recovered R10 archive is `palindromic_rank64_temporal_R10_SINGLE_STREAM_2020_full.zip`, checkpoint `r10_active.pal10` (120,658,914 bytes, SHA-256 `4e1406db323aee84e48aeabe0d5963c0454b9ed869ad6e399dc97415d6210ded`). The R10 structural suite passed 11/11 tests.

R11 retains the same 32K whole-word core, 96-D NOW state, mirrored rank-64 P/M rails, 72 long-context features, pretrained SentencePiece+raw-byte embedding and GRUCell, output layer, boundary bridge, and original AdamW optimizer moments. There is no second language model or second active checkpoint. The R10 step count remains 2,020; R11 counts begin at 0.

R11 raw-prose training preserves the exact UTF-8 byte sequence. Each non-whitespace text segment is encoded through R7's existing lossless SentencePiece+byte-fallback tokenizer; whitespace remains literal byte tokens. At each segment boundary, the original NOW trunk reads *prior* whole-word context only. A contiguous BPE stream trains the same GRU and output head. Training examples are bounded to a maximum raw subword count to avoid pathological long input segments; truncated BPTT is explicit.

## Measured local continuation (exploratory)

* **30 accepted steps**, 2 train / 2 dev / 2 test books: raw dev bits/byte 4.490499 → 4.416299; nonspace NLL 7.630764 → 7.472104. Development evaluation covered 1,034 bytes and is a very small smoke test.
* **60 more accepted steps**, 4/4/4 books: raw dev bits/byte 4.165512 → 4.070296; nonspace NLL 7.335409 → 7.123461 on 8,553 raw bytes / 64 windows.
* **40 more accepted steps**, 4/4/4 books with bounded windows and future-rail gates: raw dev bits/byte 3.720426 → 3.692748; nonspace NLL 6.689503 → 6.626670 on 8,564 raw bytes / 64 windows. The three historical future-horizon guards passed, as did the original word NLL guard.

Total **130 accepted R11 updates** on the *same* inherited checkpoint. The latest SHA-256 is `c2fa5f4673b6e747c67c41bfa07df90ba9e78e2963efc20256961aec2c779e5e`. Interrupted 120-/240-step candidates were **not** promoted and do not count.

The source and checkpoint are packaged in the R11 release archive delivered with the experiment. These results are exploratory: tiny evaluation windows, no compute-matched baseline, low nonspace top-1, and no established fluency or frontier trajectory. The test split is used only *after* each development gate, so repeated test analyses are not a blind benchmark.

## Reproduce with R11 archive contents

```bash
python source/test_r11.py . nanrouter checkpoint/r11_active.pal11
python source/r11_raw.py --root . --books nanrouter \
  --checkpoint checkpoint/r11_active.pal11 \
  --output checkpoint/r11_active.pal11 \
  --steps 40 --max-books 4 --eval 64 --span 24 --max-tokens 160
```

R11 tests check raw-byte roundtrip, SHA-256 corpus integrity, distinct book IDs/splits, checkpoint/optimizer continuity, mirror topology, and causal NOW. Candidate promotion requires **both** raw bits/byte and nonspace NLL improvements, plus the historical whole-word and future-rail nonregression gates. Failed candidates are never written over the active checkpoint.

## Next gate

Scale to all 38 exported books and the remaining NaNROUTER release batches; widen held-out windows substantially; train until a steady improvement curve emerges, then compare with a compute-matched strong streaming Transformer/SSM on the same book-disjoint corpus. Avoid promoting on space loss alone.
