# Kaggle GPU run

The CPU runner has validated the pipeline but cannot train the 100M corpus:
a 9.6M model on 4.2M BPE tokens overfits badly (train ~1.5–2.3 bits,
validation 7.29 bits). The next real run needs a GPU. Kaggle T4/P100 is the
practical free option.

## What to upload

Create a Kaggle dataset named `nanlmv3-corpus` containing:

```text
corpus_100m.txt    # ~100 MB, from nanlmv3/data/
bpe32k.json        # 2.2 MB, from the BPE runner or train_bpe.py
```

The dataset is read-only input; the trained checkpoint and metrics go to
`/kaggle/working`.

## Notebook

Use a **GPU** notebook (T4 x2 or P100), then:

```python
!git clone https://github.com/shemshallah/NaNROUTER
!pip install -q tokenizers
%cd NaNROUTER
!python nanlmv3/kaggle_train.py
```

`kaggle_train.py` expects:

```text
/kaggle/input/nanlmv3-corpus/corpus_100m.txt
/kaggle/input/nanlmv3-corpus/bpe32k.json
```

It trains the 32k BPE if the tokenizer is absent, then runs the 10M model with:

- 4-layer causal trunk, 8 heads, FF 1024
- 128-token context
- batch 16
- 20,000 steps
- AMP (CUDA mixed precision)
- dropout 0.15, weight decay 0.05
- best-validation checkpoint

Expected wall time on a T4: roughly 1–3 hours depending on the GPU and the
memory-bias CPU cost. The 100M corpus yields ~24M BPE tokens; 20k steps at
batch 16 × 128 = 41M tokens seen, about 1.7 epochs.

## API automation

To push the dataset and kernel from this machine, place the Kaggle token at:

```text
~/.kaggle/kaggle.json
```

Then:

```sh
pip install kaggle
mkdir -p kaggle_dataset
cp nanlmv3/data/corpus_100m.txt bpe32k.json kaggle_dataset/
cd kaggle_dataset
kaggle datasets init -p .
# edit dataset-metadata.json: title/slug
kaggle datasets create -p .
```

The dataset slug will be `<username>/nanlmv3-corpus`. Once it exists, the
notebook can be launched from the Kaggle UI or with `kaggle kernels push`.

## Why not CPU

The CPU run’s train/validation gap is not a bug:

- 9.6M parameters
- 4.2M training tokens
- train loss ~1.5 bits, validation 7.29 bits

A 10M model needs roughly 200M tokens for a compute-optimal run. The 100M
corpus is prepared; the missing ingredient is GPU time, not data.
