# P13 gate ledger

Status: all P13 gates are **blocked**. No P13 success is claimed.

Machine-readable source: `spec/p13-gates.json`.

The plan requires real evidence or an explicit blocked/rejected result. This
ledger records the blocked result for each remaining external gate:

| Gate | Status | Why blocked |
|---|---|---|
| Live Koyeb/NANNET0 | blocked | No live credentials, network path, or mounted runtime |
| Signed volume registry | blocked | No signed payload or trust root |
| Production MC0DB | blocked | No deployed BS0DB/MC0DB volumes |
| Frozen-model LM ablation | blocked | No frozen model/tokenizer/held-out data |
| R7 held-out experiment | blocked | No real held-out task set |
| Capacity vs SNR | blocked | No frozen model/data sweep |
| Native numeric executor | blocked | NaN0S toolchain/native executor unavailable |

There is no page-size-limit gate. The owner clarified that guest memory has no
page-size limit; the 2 MiB value is an adjustable budget, and the fixed 32 KiB
page is only the logical unit of the 8 MiB universe layout.

A gate is only moved to `passed` when its required evidence is attached to
`docs/R10_IMPLEMENTATION_EVIDENCE.md` and the test ledger. A blocked gate is not
a failure of the control plane; it is an honest statement that the evidence
does not exist yet.
