# Native head bank: pinned VM attachment with class-exact import/export

This bridge is the first direct execution connection from the HERMES
head-bank byte region to a real NaN16 worker. It uses
`runner_riddle.n16t_guest._NaN16GuestVM` (existing native C VM)
with a **configurable, explicit required guest-entry set** rather than
creating a second Python interpreter or a C head math engine.

## Execution

`NativeHeadBankGuest.observe` receives one validated
`HeadBankHandoff` and one exact `67,838 × 8` byte bank. It:

1. Pins SHA-256 of the C-core shared library, guest image and label map.
2. Validates the request's current bank hash and guest image identity.
3. Uses `nan_write_words_raw`, NOT corpus `nan_write_bytes`, to copy
   class-bearing words into word address `0x4000`.
4. For an explicitly empty genesis only, invokes native `nh_format`;
   otherwise invokes native `nh_open`, rejecting an invalid bank.
5. Calls native `nhr_attach`, then `nhr_read` to determine the
   **native** previous revision.
6. Calls native `nhr_observe(head,feature,increment,staging)`; all
   increment, slot selection, checksum and NaN class operations happen
   inside the NaN16 guest.
7. Uses `nan_read_words_raw` to return the entire revised bank and
   its SHA-256, matching a root/head/lease/generation-bound request.
8. Closes the one-operation VM without creating a second persistent model.

The output is staging evidence: `native_guest_invoked_locally=true`
and `authenticated_dispatch_verified=false`. A caller has NOT
authenticated the global router lease simply by invoking the local VM.
The authoritative `HermesDispatchJournal`, active NANNET0 lease,
single-active runner epoch, HERMES chart parent/generation fence and
explicit checkpoint/merge remain distinct preconditions.

## GitHub native proof

The workflow checks out the pinned NaN0S commit containing
`n16_head_worker.nas` and the new class-preserving raw-word C ABI,
compiles the actual C VM shared library, assembles a NaN16 worker with
pinned labels, and runs the adapter tests against that guest. It tests
virgin→gen1→gen2, head255 isolation, torn newest-slot recovery,
invalid-bank refusal and class-sensitive guest reopen. Pure unit tests
also verify that malformed hashes/lengths cannot allocate a guest VM.

This establishes a genuine **native scratch observation update**, not
language-model generalization, a native MTH operator execution, a
canonical NANNET merge, or a mathematical theorem. The next gate is
authenticated at-most-once dispatch and the atomic HERMES storage handoff.
