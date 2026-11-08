; MTH native xorshift64 forward step — native NaN16 integer instructions only.
;
; State/value representation (caller-owned memory):
;   A 64-bit value is two consecutive NaN16 words.
;     word 0 (lower address)  = bits 31..0  (low 32-bit half)
;     word 1 (higher address) = bits 63..32 (high 32-bit half)
;   Each half is carried in the 32-bit payload of a class-10 (+q/+q) word.
;   The NaN16 payload byte order is the canonical little-endian b2..b5 layout.
;   The routine reads and writes payloads only; it does not inspect or validate
;   the NaN16 head/class nibble of the input words.
;
; ABI (r13=1):
;   r1 = input state address        (2 words)
;   r2 = output state address       (2 words)
;   r3 = output 64-bit value address (2 words)
;   return r1=1 on success, r1=0 on rejection
;
; On success:
;   output_state = x_next
;   output_value = x_next   (xorshift64 emits its post-step state)
;   Both output spans are written as class-10 (+q/+q) words.
;
; On all-zero input state (x == 0):
;   r1=0
;   output_state = 0xFFFFFFFF_FFFFFFFF
;   output_value = 0xFFFFFFFF_FFFFFFFF
;   The input state words are not written.
;   The marker is two class-10 words with payload 0xFFFFFFFF in each half.
;
; Aliasing:
;   output_state and output_value may each be equal to the input span and may be
;   equal to each other. Partial overlap between the three spans is not
;   supported. Input halves are loaded before any output word is stored.
;
; Clobbers r4-r8 and flags. Preserves r2,r3,r10-r15. r1 receives the status.
;
; Algorithm (64-bit, modulo 2^64, logical right shift):
;   x ^= x << 13
;   x ^= x >> 7
;   x ^= x << 17
;
; The 32-bit half formulas used below are:
;   x << n: lo' = lo << n; hi' = (hi << n) | (lo >> (32-n))
;   x >> n: hi' = hi >> n; lo' = (lo >> n) | ((hi & ((1<<n)-1)) << (32-n))
; with n in 1..31, so no 64-bit native add or host arithmetic is required.

mth_prng_xorshift64_step:
  LD r4,r1,0                 ; r4 = low half
  LD r5,r1,1                 ; r5 = high half
  BOOL.14 r6,r4,r5           ; r6 = low | high
  CMP r6,r0
  JMP[EQ] @mth_prng_xorshift64_zero

  ; x ^= x << 13
  SHL r6,r4,13               ; low << 13
  SHR r7,r4,19               ; bits carried out of the low half
  SHL r8,r5,13               ; high << 13
  BOOL.14 r8,r8,r7           ; shifted high half
  BOOL.6 r4,r4,r6            ; low ^= low << 13
  BOOL.6 r5,r5,r8            ; high ^= high << 13

  ; x ^= x >> 7
  SHR r6,r4,7                ; low >> 7
  MOVI r7,0x7F
  BOOL.8 r8,r5,r7            ; high & 0x7F
  SHL r8,r8,25               ; carried into bit 31 of the low half
  BOOL.14 r6,r6,r8           ; shifted low half
  SHR r8,r5,7                ; high >> 7
  BOOL.6 r4,r4,r6            ; low ^= low >> 7
  BOOL.6 r5,r5,r8            ; high ^= high >> 7

  ; x ^= x << 17
  SHL r6,r4,17               ; low << 17
  SHR r7,r4,15               ; bits carried out of the low half
  SHL r8,r5,17               ; high << 17
  BOOL.14 r8,r8,r7           ; shifted high half
  BOOL.6 r4,r4,r6            ; low ^= low << 17
  BOOL.6 r5,r5,r8            ; high ^= high << 17

  ST r4,r2,0
  ST r5,r2,1
  ST r4,r3,0
  ST r5,r3,1
  MOVI r1,1
  RET

mth_prng_xorshift64_zero:
  ; Canonical rejection marker: 0xFFFFFFFF_FFFFFFFF in both output spans.
  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
  ST r4,r2,0
  ST r4,r2,1
  ST r4,r3,0
  ST r4,r3,1
  MOVI r1,0
  RET
