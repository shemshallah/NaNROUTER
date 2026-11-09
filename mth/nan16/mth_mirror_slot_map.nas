; MTH Round 037 reference-slot map over the canonical 8 MiB mirror memory.
;
; ABI (r13=1):
;   r1 = slot, 0..32384
; Success:
;   r1 = 1
;   r3 = a, 1..254
;   r4 = b, a+1..255
;   r5 = canonical pair id, 1..32640
;   r6 = pair record byte offset, 32768 + (pair id - 1) * 256
; Reject slot >= 32385 with r1=0.
;
; Slot order is the Round 037 lexical order:
;   slot 0    -> (1,2)
;   slot 253  -> (1,255)
;   slot 254  -> (2,3)
;   slot 32384-> (254,255)
;
; This is address mapping only. It reads no evidence and performs no learning.

mth_mirror_slot_map:
  MOVI r13,1
  MOVI r10,32384
  CMP r1,r10
  JMP[GT] @mth_mirror_slot_map_reject
  ADD r11,r1,r0             ; remaining
  MOVI r3,1                 ; a
mth_mirror_slot_map_row:
  MOVI r10,255
  SUB r10,r10,r3            ; width = 255-a
  CMP r11,r10
  JMP[LT] @mth_mirror_slot_map_found
  SUB r11,r11,r10
  ADD r3,r3,r13
  JMP @mth_mirror_slot_map_row
mth_mirror_slot_map_found:
  ADD r4,r3,r13             ; b = a+1+remaining
  ADD r4,r4,r11
  MOVI r10,511
  SUB r10,r10,r3            ; 511-a
  MUL r10,r3,r10            ; a*(511-a)
  SHR r10,r10,1             ; /2
  SUB r5,r4,r3
  SUB r5,r5,r13             ; b-a-1
  ADD r5,r5,r10             ; zero-based pair index
  ADD r5,r5,r13             ; canonical pair id
  SHL r6,r5,8               ; pair id * 256
  MOVI r10,256
  SUB r6,r6,r10             ; (pair id-1)*256
  MOVI r10,32768
  ADD r6,r6,r10             ; record byte offset
  MOVI r1,1
  RET

mth_mirror_slot_map_reject:
  MOVI r1,0
  RET
