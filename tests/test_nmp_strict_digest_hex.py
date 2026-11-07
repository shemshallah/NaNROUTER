"""Regression: NMP evidence digests must be exactly 64 ASCII hex characters.

Python int(value, 16) accepts trailing whitespace; transport digest fields
must not inherit that more permissive syntax.
"""
from types import SimpleNamespace

import pytest

from runner_riddle.nmp_http import NmpHttpError, _validate_execution_evidence


def _evidence():
    return {
        "schema": "nanrouter.native-kernel-execution.v1",
        "packet_id": "packet-1",
        "function_id": "math.vector.add.v1",
        "program_id": 78,
        "lease_epoch": 2,
        "lease_owner": "worker-1",
        "guest_steps": 10,
        "dimension": 2,
        "output_kind": 4,
        "output_count": 2,
        "output_digest": "a" * 64,
        "guest_image_digest": "b" * 64,
        "guest_source_digest": "c" * 64,
    }


def _verify(evidence, **pins):
    return _validate_execution_evidence(
        evidence,
        packet=SimpleNamespace(packet_id="packet-1", function_id="math.vector.add.v1"),
        expected_program_id=78,
        result_digest="a" * 64,
        lease_epoch=2,
        lease_owner="worker-1",
        **pins,
    )


def test_exact_ascii_hex_is_accepted():
    result = _verify(
        _evidence(),
        expected_image_digest="B" * 64,
        expected_source_digest="C" * 64,
    )
    assert result["guest_image_digest"] == "b" * 64


@pytest.mark.parametrize("field", ["output_digest", "guest_image_digest", "guest_source_digest"])
def test_evidence_rejects_trailing_whitespace(field):
    evidence = _evidence()
    evidence[field] = evidence[field][:-1] + " "
    with pytest.raises(NmpHttpError, match="SHA-256 hex"):
        _verify(evidence)


@pytest.mark.parametrize("pin", ["expected_image_digest", "expected_source_digest"])
def test_pins_reject_trailing_whitespace(pin):
    with pytest.raises(NmpHttpError, match="server-pinned"):
        _verify(_evidence(), **{pin: "a" * 63 + " "})


def test_evidence_rejects_prefix_syntax():
    evidence = _evidence()
    evidence["output_digest"] = "0x" + "a" * 62
    with pytest.raises(NmpHttpError, match="SHA-256 hex"):
        _verify(evidence)
