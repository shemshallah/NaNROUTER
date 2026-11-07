# MTH R9 encode/decode linear kernels

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

This slice adds the two dense linear maps needed by an R9 adapter projection pair:

```
mth_encode256_128_f32:  y[i] = b[i] + sum_{j=0}^{255} W[i,j] * x[j]   (256 -> 128)
mth_decode128_256_f32:  y[i] = b[i] + sum_{j=0}^{127} W[i,j] * z[j]   (128 -> 256)
```

Both are leaf NaN16 float32 kernels. They perform no host math and call no other kernels. The two maps are independent dense matrices; nothing here ties their weights, trains them, or composes them with the residual/readout contract in `docs/MTH_LM_ADAPTER_ABI.md`. An adapter built from these kernels remains disabled until its own contract and evidence gates pass.

Files:

- `mth/nan16/mth_encode256_128.nas`
- `mth/nan16/mth_decode128_256.nas`
- `mth/tests/mth_encode_decode_test.nas`

## 2. Encode ABI

| Register | Meaning |
|---|---|
| `r1` | `W`, 32,768 float32, row-major 128 x 256 |
| `r2` | `x`, 256 float32 |
| `r3` | `b`, 128 float32 bias |
| `r4` | `y`, 128 float32 output |
| `r13` | 1 |
| return | `r1=1` |
| clobbers | `r1`-`r12`, `r14`; preserves `r13` and `r15` |

Working set: 32,768 + 256 + 128 + 128 = 33,280 words. The kernel walks rows in increasing `i` and columns in increasing `j`. One accumulator per row is seeded with `b[i]`, then each column performs one rounded `FMUL` and one rounded `FADD`, evaluating `b[i] + W[i,0]x[0] + ... + W[i,255]x[255]`. There is no FMA, no reassociation, and no specialization for sparsity.

## 3. Decode ABI

| Register | Meaning |
|---|---|
| `r1` | `W`, 32,768 float32, row-major 256 x 128 |
| `r2` | `z`, 128 float32 |
| `r3` | `b`, 256 float32 bias |
| `r4` | `y`, 256 float32 output |
| `r13` | 1 |
| return | `r1=1` |
| clobbers | `r1`-`r12`, `r14`; preserves `r13` and `r15` |

Working set: 32,768 + 128 + 256 + 256 = 33,408 words. Row/column ordering and the seeded-bias accumulator are identical to encode, with 256 rows and 128 columns: `b[i] + W[i,0]z[0] + ... + W[i,127]z[127]`.

Both kernels are leaves and always return `r1=1`; there is no failure path. Callers must supply `r13=1`, keep `W` read-only, and use distinct non-overlapping spans for `W`, the input vector, the bias, and the output.

## 4. Fixture

`mth/tests/mth_encode_decode_test.nas` reuses one 32,768-word `W` buffer for both cases.

Encode case:

- `W[i,i]=1` for `i=0..127` and zero elsewhere (128 x 256 rectangular identity, row stride 256, diagonal stride 257);
- `b=1` for all 128, `x=1` for all 256;
- expected `y[i]=2` for all 128.

Decode case:

- `W[i,i]=1` for `i=0..127` and zero elsewhere (256 x 128 rectangular identity, row stride 128, diagonal stride 129);
- `b=1` for all 256, `z=1` for all 128;
- expected `y[0..127]=2` and `y[128..255]=1`.

The result sweeps are exhaustive, so they include the sample and endpoint positions 0, 64, 127, 128, and 255. The fixture layout allocates `W` at word 512, a 256-word vector slot at 33280, a 256-word bias slot at 33536, and a 256-word output slot at 33792; strings begin at 34048 and the emitted image is 34,060 words. Only the 128-word bias/output prefixes are used by encode; decode uses the full 256-word slots.

## 5. Local evidence

Assemble and run:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_encode_decode_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/encode_decode.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/encode_decode.nan \
  --steps 30000000 --serial
```

Observed output:

```
words 34060
[nan_cli] nan-text: 996358 steps, rc=3, pc=184, trap=''
MTH ENCODE DECODE PASS
```

`nmk.awk -v CMD=check` reports 0 disassembly mismatches on the emitted image. The 996,358 guest steps are well under the 30,000,000-step budget; `rc=3` is `HALT` and `nan_cli` exits 0.

## 6. Limitations

- **Dense only.** Both kernels read a full dense float32 matrix every call. There is no sparse, low-rank, quantized, or paged path, and no blocking/cache optimization.
- **Fixed shapes only.** Encode is exactly 128 x 256 -> 128 and decode is exactly 256 x 128 -> 256. Larger or differently shaped maps require separate kernels or caller-side paging.
- **No training.** These are forward inference kernels only. There is no gradient, update, optimizer, initialization, or weight tying; the fixture builds weights in guest code solely as an oracle.
- **Prototype.** The kernels are not registered as an enabled R9 adapter, make no model-quality claim, and do not implement the residual `h + beta*C*u` composition. They also provide no activation, normalization, or softmax.
- **No validation.** Overlap, aliasing, alignment, NaN, Inf, denormal, and range checks are caller preconditions. Behavior for aliased spans is unspecified.
- **Accumulation order.** Serial in increasing `j` with one accumulator per row; results need not be bitwise identical to BLAS, FMA, pairwise, or otherwise reordered implementations.
- **Register contract.** Callers must set `r13=1`; both kernels clobber `r1`-`r12` and `r14` and preserve `r15`.
