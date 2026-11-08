"""Three noninterchangeable counts for the ONE 256-head palindrome universe.

A fixed-point head is always present in the 16-bit topology. This file is
an additive, read-only description of local *role* and curriculum allocation.
It is not a second chart, mutable routing authority, NANNET lease, grant,
MTH execution gate or implicit permission to write an MC0DB MathLeaf.
"""
from __future__ import annotations

import hashlib
import json

from .mirror_point_register import (
    HEADS, NANNET_HEAD, TOPOLOGY_DIGEST, MirrorPointError,
    MirrorRegister,
)

SCHEMA = "nanrouter.local-head-role-contract/1"
BSR_HEADS = (0, 4, 5, 6, 7, 8)
BSR_SLOT_BY_HEAD = {h: slot for slot, h in enumerate(BSR_HEADS)}
ROOT_RESERVED = frozenset((NANNET_HEAD,))
CURRICULUM_RESERVED = frozenset(BSR_HEADS)

assert HEADS == 256
assert NANNET_HEAD == 0
assert len(CURRICULUM_RESERVED) == 6
assert all(0 <= h < HEADS for h in CURRICULUM_RESERVED)
assert ROOT_RESERVED <= CURRICULUM_RESERVED

_BINDING_HEADS = tuple(h for h in range(HEADS) if h not in ROOT_RESERVED)
_CURRICULUM_HEADS = tuple(h for h in range(HEADS)
                          if h not in CURRICULUM_RESERVED)
_CONTRACT = {
    "schema": SCHEMA,
    "topology_sha256": TOPOLOGY_DIGEST,
    "physical_palindrome_heads": HEADS,
    "nannet_root_head": NANNET_HEAD,
    "bsr_control_head_indices": list(BSR_HEADS),
    "mp_microtable_writer_eligible": len(_BINDING_HEADS),
    "boolean_curriculum_eligible": len(_CURRICULUM_HEADS),
}
RAW_CONTRACT = json.dumps(_CONTRACT, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
CONTRACT_SHA256 = hashlib.sha256(
    b"nanrouter.local-head-role-contract/1\0" + RAW_CONTRACT
).hexdigest()


def describe_head(head: int) -> dict:
    if type(head) is not int or not 0 <= head < HEADS:
        raise MirrorPointError("local head index must be 0..255")
    table = MirrorRegister.head(head)
    writable = head not in ROOT_RESERVED
    # This must agree with the existing microtable; we do NOT grant its
    # capability and we never bypass MathStore/NANNET authorization.
    if (head in table.as_dict()["writable_heads"]) != writable:
        raise MirrorPointError("head role disagrees with mirror microtable")
    return {
        "schema": SCHEMA,
        "head_index": head,
        "route": f"HW0:{head}",
        "canonical_cell": head,
        "raw_address": table.canonical_address,
        "physical_palindrome_exists": True,
        "nannet_root_head": head == NANNET_HEAD,
        "bsr_control_head": head in CURRICULUM_RESERVED,
        "bsr_wire_slot": BSR_SLOT_BY_HEAD.get(head),
        "mp_microtable_writer_eligible": writable,
        "boolean_curriculum_eligible": head not in CURRICULUM_RESERVED,
        "topology_sha256": TOPOLOGY_DIGEST,
        "role_contract_sha256": CONTRACT_SHA256,
        "grants_permission": False,
        "native_mth_executed": False,
    }


def role_summary() -> dict:
    return {
        **_CONTRACT,
        "bsr_wire_slot_to_head": list(BSR_HEADS),
        "mp_writable_head_indices": list(_BINDING_HEADS),
        "boolean_curriculum_head_indices": list(_CURRICULUM_HEADS),
        "role_contract_sha256": CONTRACT_SHA256,
        "physical_chart_copies_created": 0,
        "grants_permission": False,
        "native_mth_executed": False,
    }
