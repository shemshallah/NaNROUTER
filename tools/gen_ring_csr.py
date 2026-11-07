#!/usr/bin/env python3
"""Generate the deterministic C255 head-ring CSR and 8 MiB universe page map.

The head-only graph is the undirected cycle C255: head ``i`` is connected to
``(i - 1) mod 255`` and ``(i + 1) mod 255``.  Both directions of every
undirected edge are stored in canonical CSR, so 255 heads produce 510 directed
entries and a 256-word ``row_offsets`` array.

The single NANNET port is mathematical ring position 255.  It is not a head.
The port attachment policy is explicit and versioned: by default the port is
coupled to head 0 with weight 1.0.

This script performs only index generation and JSON serialization.  It does not
perform graph, spectral, or wave mathematics on the host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "spec" / "ring-255.json"

VERSION = "nanrouter.ring-c255.v1"
PORT_POLICY_VERSION = "nanrouter.nannet-port-coupling.v1"
PORT_POLICY_NAME = "single-attachment-head-0"

HEAD_COUNT = 255
RING_POSITION_COUNT = 256
NANNET_PORT_POSITION = 255
PAGE_SIZE_BYTES = 32 * 1024
PAGE_COUNT = 256
UNIVERSE_SIZE_BYTES = PAGE_SIZE_BYTES * PAGE_COUNT

DIGEST_METHOD: dict[str, str] = {
    "algorithm": "sha256",
    "canonical_form": (
        "UTF-8 JSON of this document with the top-level 'digest' field removed, "
        "keys sorted lexicographically, separators ',' and ':', ensure_ascii=true, "
        "allow_nan=false"
    ),
    "digest_encoding": "lowercase hexadecimal",
}


def build_row_offsets() -> list[int]:
    """Return 256 U32 row offsets for 255 degree-2 head rows."""
    return [2 * head for head in range(HEAD_COUNT + 1)]


def head_neighbors(head: int) -> list[int]:
    """Return the two C255 neighbors of a head in canonical sorted order."""
    return sorted({(head - 1) % HEAD_COUNT, (head + 1) % HEAD_COUNT})


def build_neighbors() -> list[int]:
    """Return the 510 directed CSR neighbor entries for C255."""
    return [
        neighbor
        for head in range(HEAD_COUNT)
        for neighbor in head_neighbors(head)
    ]


def build_ring_positions() -> list[dict[str, Any]]:
    """Return the 256-position ring readout layout: 255 heads plus the port."""
    positions: list[dict[str, Any]] = [
        {"position": position, "kind": "head", "head": position}
        for position in range(HEAD_COUNT)
    ]
    positions.append({
        "position": NANNET_PORT_POSITION,
        "kind": "nannet_port",
        "head": None,
    })
    return positions


def build_port_policy() -> dict[str, Any]:
    """Return the explicit, versioned NANNET port attachment policy."""
    return {
        "version": PORT_POLICY_VERSION,
        "name": PORT_POLICY_NAME,
        "attachment_head": 0,
        "weight": 1.0,
    }


def build_port_couplings() -> list[dict[str, Any]]:
    """Return the port coupling edge list under the default policy."""
    return [{
        "port_position": NANNET_PORT_POSITION,
        "head": 0,
        "weight": 1.0,
    }]


def build_page_map() -> list[dict[str, Any]]:
    """Return 256 pages of 32 KiB: page i -> head i, page 255 -> NANNET."""
    pages: list[dict[str, Any]] = [
        {
            "page": page,
            "kind": "head",
            "head": page,
            "size_bytes": PAGE_SIZE_BYTES,
            "offset_bytes": page * PAGE_SIZE_BYTES,
        }
        for page in range(HEAD_COUNT)
    ]
    pages.append({
        "page": NANNET_PORT_POSITION,
        "kind": "nannet_port",
        "head": None,
        "size_bytes": PAGE_SIZE_BYTES,
        "offset_bytes": NANNET_PORT_POSITION * PAGE_SIZE_BYTES,
    })
    return pages


def canonical_json_bytes(document: dict[str, Any]) -> bytes:
    """Serialize the digest payload using the documented canonical form."""
    payload = {key: value for key, value in document.items() if key != "digest"}
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def compute_digest(document: dict[str, Any]) -> str:
    """Return the lowercase SHA-256 digest of the canonical digest payload."""
    return hashlib.sha256(canonical_json_bytes(document)).hexdigest()


def build_document() -> dict[str, Any]:
    """Build the complete versioned ring descriptor and bind its digest."""
    row_offsets = build_row_offsets()
    neighbors = build_neighbors()
    ring_positions = build_ring_positions()
    port_couplings = build_port_couplings()
    page_map = build_page_map()

    document: dict[str, Any] = {
        "version": VERSION,
        "counts": {
            "head_count": HEAD_COUNT,
            "head_index_min": 0,
            "head_index_max": HEAD_COUNT - 1,
            "ring_position_count": len(ring_positions),
            "nannet_port_count": 1,
            "nannet_port_position": NANNET_PORT_POSITION,
            "csr_row_count": HEAD_COUNT,
            "row_offset_count": len(row_offsets),
            "directed_edge_count": len(neighbors),
            "neighbor_count": len(neighbors),
            "undirected_edge_count": HEAD_COUNT,
            "port_coupling_count": len(port_couplings),
            "page_count": len(page_map),
            "page_size_bytes": PAGE_SIZE_BYTES,
            "universe_size_bytes": UNIVERSE_SIZE_BYTES,
        },
        "row_offsets": row_offsets,
        "neighbors": neighbors,
        "ring_positions": ring_positions,
        "port_policy": build_port_policy(),
        "port_couplings": port_couplings,
        "page_map": page_map,
        "digest_method": dict(DIGEST_METHOD),
    }
    document["digest"] = compute_digest(document)
    return document


def render_document(document: dict[str, Any] | None = None) -> str:
    """Render the descriptor as stable, pretty-printed JSON with a final LF."""
    if document is None:
        document = build_document()
    return json.dumps(
        document,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ) + "\n"


def write_document(path: str | Path = DEFAULT_OUT) -> dict[str, Any]:
    """Generate the descriptor and write it to ``path`` deterministically."""
    document = build_document()
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        render_document(document), encoding="utf-8", newline="\n"
    )
    return document


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the canonical C255 head-ring CSR and page map."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="output JSON path (default: spec/ring-255.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    document = write_document(args.out)
    print(f"wrote {args.out} digest={document['digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
