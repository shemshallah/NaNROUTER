"""Run by the GitHub cross-repo workflow after checkout of HERMES.

Checks topology and writer parity without trusting a second chart, granting
authorization or conflating BSR control slots with hardware node points.
"""
from nanlmind_hermes.mirror_topology import (
    MirrorTopology, TOPOLOGY_DIGEST as HERMES_TOPOLOGY,
)
from runner_riddle.head_role_contract import BSR_HEADS, describe_head, role_summary
from runner_riddle.mirror_point_register import (
    MirrorRegister, PAIR_COUNT, TOPOLOGY_DIGEST,
)


def main():
    assert HERMES_TOPOLOGY == TOPOLOGY_DIGEST
    summary = role_summary()
    assert summary["physical_palindrome_heads"] == 256
    assert summary["mp_microtable_writer_eligible"] == 255
    assert summary["boolean_curriculum_eligible"] == 250
    assert summary["bsr_control_head_indices"] == list(BSR_HEADS)
    assert not summary["grants_permission"]
    for head in range(256):
        r = MirrorRegister.head(head).as_dict()
        h = MirrorTopology.head(head).as_dict()
        role = describe_head(head)
        for key in ("canonical_address", "canonical_cell", "addresses",
                    "writable_heads", "topology_sha256"):
            assert r[key] == h[key], ("head-microtable mismatch", head, key)
        assert role["mp_microtable_writer_eligible"] == bool(r["writable_heads"])
        assert role["boolean_curriculum_eligible"] == (head not in BSR_HEADS)
    for mp in range(PAIR_COUNT):
        r = MirrorRegister.mp(mp).as_dict()
        h = MirrorTopology.mp(mp).as_dict()
        for key in ("canonical_address", "canonical_cell", "addresses",
                    "heads", "writable_heads", "topology_sha256"):
            assert r[key] == h[key], ("MP mismatch", mp, key)
    print("PASS: 256 router/HERMES head roles; 32,640 MP writer ACLs; "
          "255 MP-writers, 250 curriculum heads, zero second charts")


if __name__ == "__main__":
    main()
