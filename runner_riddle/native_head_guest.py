"""Pinned NaN16 VM host bridge: class-exact 255-head bank observation.

The native NaN16 guest performs ALL checksum, slot selection, generation and
counter arithmetic. Python only verifies an existing pinned request, imports
opaque raw eight-byte words, schedules guest calls, exports the bank and
collects digest-bound evidence. This is NOT a network-authenticated dispatch
nor a canonical chart commit. The caller must still authenticate a current
NaNROUTER lease, at-most-once journal and chart generation before publishing.
"""
from __future__ import annotations

import hashlib
import threading
from typing import Callable

from .head_bank_handoff import (
    BANK_BYTES, BANK_WORDS, HeadBankHandoff, HeadBankHandoffError,
    check_native_observation_receipt,
)
from .hermes_native import _pinned_file, HermesNativeError
from .n16t_guest import _NaN16GuestVM, _load_labels, N16TGuestRuntimeError

BANK_BASE = 0x4000
STAGING_BASE = 0x1000
READBACK_BASE = 0x2000
STAGING_WORDS = 128
REQUIRED_ENTRIES = (
    "nh_format", "nh_open", "nhr_attach", "nhr_observe", "nhr_read"
)


class NativeHeadBankError(ValueError):
    pass


class NativeHeadBankGuest:
    """One native guest worker, one opaque update, no alternate model state."""

    def __init__(self, *, library_path, library_sha256,
                 image_path, image_sha256, labels_path, labels_sha256,
                 vm_factory: Callable = _NaN16GuestVM):
        try:
            self.library = _pinned_file(library_path, library_sha256, "raw VM library")
            self.image = _pinned_file(image_path, image_sha256, "NaN16 head guest")
            self.labels = _pinned_file(labels_path, labels_sha256, "head guest labels")
        except HermesNativeError as exc:
            raise NativeHeadBankError("native guest binary/label pin validation failed") from exc
        self.library_sha256 = library_sha256
        self.image_sha256 = image_sha256
        self.labels_sha256 = labels_sha256
        labels = _load_labels(__import__("pathlib").Path(self.labels))
        if any(name not in labels for name in REQUIRED_ENTRIES):
            raise NativeHeadBankError("pinned native worker missing required entry")
        if not callable(vm_factory):
            raise NativeHeadBankError("native VM factory is not callable")
        self._factory = vm_factory
        self._lock = threading.RLock()

    @staticmethod
    def _call(vm, entry, registers):
        vm.call(entry, registers)
        status = vm.reg(5)
        if status != 0:
            raise NativeHeadBankError(
                f"native NaN16 {entry} rejected scratch operation (status {status})"
            )
        return vm.reg(6)

    def observe(self, *, request: HeadBankHandoff,
                raw_bank: bytes, allow_genesis_format: bool = False) -> dict:
        """Run exactly one class-bearing guest learning observation.

        This method is intentionally staging-only: it never mutates the chart,
        changes MC0DB, answers the user, or confirms NANNET approval. The
        caller must check the receipt, stage into the chart under its current
        parent/generation fence and enforce durable at-most-once semantics.
        """
        if not isinstance(request, HeadBankHandoff):
            raise NativeHeadBankError("validated handoff required")
        if type(raw_bank) is not bytes or len(raw_bank) != BANK_BYTES:
            raise NativeHeadBankError("opaque head bank length mismatch")
        if type(allow_genesis_format) is not bool:
            raise NativeHeadBankError("genesis format permission must be boolean")
        before_hash = hashlib.sha256(raw_bank).hexdigest()
        if before_hash != request.bank_before_sha256:
            raise NativeHeadBankError("stale or mismatched head bank SHA-256")
        if request.native_image_sha256 != self.image_sha256:
            raise NativeHeadBankError("native guest image digest not pinned to request")
        if raw_bank == bytes(BANK_BYTES) and not allow_genesis_format:
            raise NativeHeadBankError("unformatted bank: explicit genesis needed")
        if raw_bank != bytes(BANK_BYTES) and allow_genesis_format:
            raise NativeHeadBankError("refusing destructive format of nonempty bank")
        if BANK_BASE + BANK_WORDS > 0x00400000:
            raise NativeHeadBankError("native VM bank does not fit guest memory")

        with self._lock:
            vm = None
            try:
                vm = self._factory(
                    self.library, self.image, self.labels,
                    required_labels=REQUIRED_ENTRIES
                )
                if allow_genesis_format:
                    self._call(vm, "nh_format", {1: BANK_BASE})
                else:
                    vm.write_raw_words(BANK_BASE, raw_bank)
                    self._call(vm, "nh_open", {1: BANK_BASE})
                self._call(vm, "nhr_attach", {1: BANK_BASE})
                # Query native previous revision. Empty heads return status 2,
                # which is an *expected guest status*, not an invented reset.
                vm.call("nhr_read", {1: request.head_index,
                                     2: READBACK_BASE})
                old_status = vm.reg(5)
                if old_status == 2:
                    before_generation = 0
                elif old_status == 0:
                    before_generation = vm.reg(6)
                    if before_generation < 1:
                        raise NativeHeadBankError("native committed head lacks generation")
                else:
                    raise NativeHeadBankError("native prior head read refused")
                after_generation = self._call(
                    vm, "nhr_observe",
                    {1: request.head_index, 2: request.feature_index,
                     3: request.increment, 4: STAGING_BASE},
                )
                if after_generation != before_generation + 1:
                    raise NativeHeadBankError("guest head generation did not advance")
                # C API copies the complete class-bearing NaN16 word faces.
                output = vm.read_raw_words(BANK_BASE, BANK_WORDS)
                if type(output) is not bytes or len(output) != BANK_BYTES:
                    raise NativeHeadBankError("native bank export is incomplete")
                after_hash = hashlib.sha256(output).hexdigest()
                if after_hash == before_hash:
                    raise NativeHeadBankError("guest update did not change state")
                source = request.prepared()
                receipt = {
                    **source, "kind": "native-head-observation",
                    "native_status": 0,
                    "head_generation_before": before_generation,
                    "head_generation_after": after_generation,
                    "bank_after_sha256": after_hash,
                    "guest_library_sha256": self.library_sha256,
                    "guest_labels_sha256": self.labels_sha256,
                    "host_transport": "raw-eight-byte-nan16-words",
                    "native_guest_invoked_locally": True,
                    "authenticated_dispatch_verified": False,
                    "canonical_training_committed": False,
                    "nannet_merge_issued": False,
                }
                check_native_observation_receipt(request, receipt)
                return {"schema": "nanrouter.native-head-guest-transport/1",
                        "receipt": receipt, "raw_bank": output,
                        "native_guest_invoked_locally": True,
                        "authenticated_dispatch_verified": False,
                        "canonical_training_committed": False}
            except (OSError, ValueError, N16TGuestRuntimeError, HeadBankHandoffError) as exc:
                raise NativeHeadBankError("NaN16 head-bank guest update failed: " +
                                          str(exc)) from exc
            finally:
                if vm is not None:
                    vm.close()
