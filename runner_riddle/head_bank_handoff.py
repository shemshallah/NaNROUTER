"""Structural handoff contract for NaN16 native head-bank learning evidence.

This is a *precondition validator*, not a native guest, math-validity engine,
authenticated dispatch journal, or proof checker. It binds one prospective
native guest update to a chart snapshot, a lease, and an observation digest.
Only the existing NaNROUTER/NMP/lease/native guest execution chain can execute
or authorize a mathematical operation. A syntactically valid receipt does NOT
attest that a guest executed; it must arrive through authenticated dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping

HEADS = 255
BANK_WORDS = 67838
BANK_BYTES = BANK_WORDS * 8
BANK_OFFSET = 0x640000
BANK_END = BANK_OFFSET + BANK_BYTES
BANK_GUEST_WORD_OFFSET = BANK_OFFSET // 8
SCHEMA = "nanrouter.native-head-handoff/1"
SHA256 = re.compile(r"[0-9a-f]{64}\\Z")


class HeadBankHandoffError(ValueError):
    pass


def _digest(value, label):
    if type(value) is not str or SHA256.fullmatch(value) is None:
        raise HeadBankHandoffError(f"{label}: expected lowercase sha256")
    return value


def _integer(value, label, low, high=(1 << 63) - 1):
    if type(value) is not int or not low <= value <= high:
        raise HeadBankHandoffError(f"{label}: out of bound integer")
    return value


def _id(value, label):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_.:-]{12,128}", value):
        raise HeadBankHandoffError(f"{label}: invalid bound identifier")
    return value


@dataclass(frozen=True)
class HeadBankHandoff:
    """One proposed update, under an externally authenticated active lease."""
    universe_id: str
    installation_id: str
    dispatch_id: str
    lease_id: int
    lease_generation: int
    ring_epoch: int
    head_index: int
    feature_index: int
    increment: int
    parent_root_sha256: str
    bank_before_sha256: str
    chart_generation: int
    observation_sha256: str
    native_image_sha256: str

    def __post_init__(self):
        _id(self.universe_id, "universe_id")
        _id(self.installation_id, "installation_id")
        _id(self.dispatch_id, "dispatch_id")
        _integer(self.lease_id, "lease_id", 1)
        _integer(self.lease_generation, "lease_generation", 1)
        _integer(self.ring_epoch, "ring_epoch", 1)
        _integer(self.head_index, "head_index", 1, HEADS)
        _integer(self.feature_index, "feature_index", 0, 127)
        _integer(self.increment, "increment", 1, 255)
        _integer(self.chart_generation, "chart_generation", 0)
        for name in ("parent_root_sha256", "bank_before_sha256",
                     "observation_sha256", "native_image_sha256"):
            _digest(getattr(self, name), name)

    def prepared(self):
        """Stable, content-bound task envelope; no execution assertion."""
        body = {
            "schema": SCHEMA,
            "kind": "observation-scoreboard",
            "universe_id": self.universe_id,
            "installation_id": self.installation_id,
            "dispatch_id": self.dispatch_id,
            "lease_id": self.lease_id,
            "lease_generation": self.lease_generation,
            "ring_epoch": self.ring_epoch,
            "head_index": self.head_index,
            "feature_index": self.feature_index,
            "increment": self.increment,
            "parent_root_sha256": self.parent_root_sha256,
            "bank_before_sha256": self.bank_before_sha256,
            "chart_generation": self.chart_generation,
            "observation_sha256": self.observation_sha256,
            "native_image_sha256": self.native_image_sha256,
            "bank_offset": BANK_OFFSET,
            "bank_end_exclusive": BANK_END,
            "bank_words": BANK_WORDS,
            "guest_word_offset": BANK_GUEST_WORD_OFFSET,
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        body["request_sha256"] = hashlib.sha256(canonical).hexdigest()
        body["execution_authorized"] = False
        body["native_execution_verified"] = False
        body["mathematical_validity"] = None
        return body


def check_native_observation_receipt(expected: HeadBankHandoff,
                                     receipt: Mapping) -> dict:
    """Check binding fields only; never interpret native NaN payloads.

    The caller MUST verify the guest's authenticated identity and the
    at-most-once journal before this check. It MUST independently verify
    the raw resulting bank hash after native VM writes; this routine only
    binds the reported hash. It cannot promote math rules.
    """
    if not isinstance(expected, HeadBankHandoff) or not isinstance(receipt, Mapping):
        raise HeadBankHandoffError("handoff and receipt required")
    task = expected.prepared()
    names = ("schema", "universe_id", "installation_id", "dispatch_id",
             "lease_id", "lease_generation", "ring_epoch", "head_index",
             "feature_index", "increment", "parent_root_sha256",
             "bank_before_sha256", "chart_generation", "observation_sha256",
             "native_image_sha256", "request_sha256")
    for name in names:
        if type(receipt.get(name)) is not type(task[name]) or receipt.get(name) != task[name]:
            raise HeadBankHandoffError("guest receipt binding mismatch: " + name)
    if receipt.get("kind") != "native-head-observation":
        raise HeadBankHandoffError("unexpected receipt kind")
    if receipt.get("native_status") != 0 or type(receipt.get("native_status")) is not int:
        raise HeadBankHandoffError("native operation not reported successful")
    before_generation = _integer(receipt.get("head_generation_before"),
                                 "head_generation_before", 0, 0x7FFFFFFF)
    after_generation = _integer(receipt.get("head_generation_after"),
                                "head_generation_after", 1, 0x7FFFFFFF)
    if after_generation != before_generation + 1:
        raise HeadBankHandoffError("native head revision did not advance")
    new_hash = _digest(receipt.get("bank_after_sha256"), "bank_after_sha256")
    if new_hash == expected.bank_before_sha256:
        raise HeadBankHandoffError("native observation did not change bank bytes")
    # This receipt cannot infer successful MTH preflight, NANNET merge,
    # semantic understanding or language-generation training.
    return {
        "schema": "nanrouter.native-head-receipt-binding/1",
        "request_sha256": task["request_sha256"],
        "bank_after_sha256": new_hash,
        "head_generation_after": after_generation,
        "bindings_consistent": True,
        "native_execution_attested": False,
        "canonical_training_committed": False,
        "mathematical_rule_promoted": False,
    }
