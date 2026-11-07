# K256 matrix-free pair-space ABI v1

Status: source-written; canonical native verification pending.

## Operator

For the K256 Laplacian (L=256I-J), the pair-space operator is

\[
L_{pair}(U)=LU+UL^T=512U-\operatorname{colsum}(U)-\operatorname{rowsum}(U).
\]

The implementation uses two 256-element sum vectors and three linear passes over the 256×256 input. It never materializes a Kronecker matrix.

## ABI

- Input: 65,536 row-major signed I32 Q16.16 words.
- Output: 65,536 signed I32 Q16.16 words.
- Workspaces: 256 signed I32 row sums and 256 signed I32 column sums.
- Scratch: 16 words.
- Input domain: raw values in [-2^20,+2^20].
- Return: 1 success, 0 invalid input state.
- r1=input, r2=output, r3=row sums, r4=column sums, r5=scratch, r13=1.
- All input validation precedes output writes. All spans must be disjoint.

## Exact range proof

For |Uij|≤2^20, each row and column sum is bounded by 2^28 and 512Uij by 2^29. Therefore every output lies within ±2^30 and signed I32 arithmetic is exact.

This is the closed-form K256 special case. It does not implement a generic sparse-CSR pair-space action for arbitrary L.

## Fixture

The fixture sets only U[0,0]=1. It checks:
- Y[0,0]=510;
- Y[0,1]=−1 and Y[1,0]=−1;
- Y[1,1]=0;
- row_sum[0]=column_sum[0]=1.
