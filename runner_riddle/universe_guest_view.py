"""Host-only guest view over the canonical 8 MiB universe map.

This additive adapter projects :mod:`runner_riddle.universe_map` into one
deterministic, JSON-safe descriptor for guest addressing.  It is address
bookkeeping only: it never executes a kernel, evaluates a relation, or claims
that a host-side mapping is native execution.  Native MTH preflight and the
NaN16 guest remain the only execution authorities.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import universe_map
from .mirror_point_register import MirrorRegister

SCHEMA = "nanrouter.universe-guest-view.v1"
VIEW_KIND = "host_only_guest_universe_view"

PAGE_BYTES = universe_map.PAGE_BYTES
WORD_BYTES = universe_map.WORD_BYTES
PAGE_WORDS = universe_map.PAGE_WORDS
UNIVERSE_PAGES = universe_map.UNIVERSE_PAGES
UNIVERSE_BYTES = universe_map.UNIVERSE_BYTES
UNIVERSE_WORDS = universe_map.UNIVERSE_WORDS
CANONICAL_CELLS = universe_map.CANONICAL_CELLS
FIXED_POINTS = universe_map.FIXED_POINTS
PAIR_COUNT = universe_map.PAIR_COUNT
REAL_HEADS = universe_map.REAL_HEADS
NANNET0_HEAD = universe_map.NANNET0_HEAD
NANNET0_PAGE = universe_map.NANNET0_PAGE
NANNET0_RING_POSITION = universe_map.NANNET0_RING_POSITION
MAX_LAYER = universe_map.MAX_LAYER
ROUTE_ROOT = universe_map.ROUTE_ROOT

FULL_ADDRESS_SPACE_BYTES = UNIVERSE_BYTES
FULL_ADDRESS_SPACE_WORDS = UNIVERSE_WORDS
NANNET0_ALIASES = ("HW0:0", "page:255", "ring:255")


class UniverseGuestViewError(ValueError):
    """A page, cell, layer, alias, raw address, or view is outside the map."""


def _int(value: Any, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise UniverseGuestViewError(
            f"{name} must be an integer {minimum}..{maximum}"
        )
    return value


def _layer(value: Any) -> int | None:
    if value is None:
        return None
    return _int(value, "layer", 0, MAX_LAYER)


def _canonical_json(value: Any, *, indent: int | None = None) -> str:
    if indent is None:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    return json.dumps(
        value,
        sort_keys=True,
        indent=indent,
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _page_dict(page_id: int) -> dict[str, Any]:
    record = universe_map.page(page_id)
    value = record.as_dict()
    value["page_bytes"] = PAGE_BYTES
    value["page_words"] = PAGE_WORDS
    value["offset_end_bytes"] = record.offset_bytes + PAGE_BYTES
    value["offset_end_words"] = record.offset_words + PAGE_WORDS
    value["covers_full_page"] = True
    return value


def _point_dict(canonical_cell: int, layer: int | None = None) -> dict[str, Any]:
    record = universe_map.point(canonical_cell)
    value = record.as_dict()
    value["offset_words"] = record.guest_word
    value["page_offset_words"] = record.word
    value["page_offset_bytes"] = record.word * WORD_BYTES
    if layer is not None:
        value["layer"] = layer
        value["layer_route"] = record.route + f"::L{layer}"
    return value


def page_view(page_id: int) -> dict[str, Any]:
    """Return one complete page descriptor with byte and word offsets."""
    return _page_dict(_int(page_id, "page", 0, UNIVERSE_PAGES - 1))


def point_view(canonical_cell: int, layer: int | None = None) -> dict[str, Any]:
    """Return one relation point and its NANNET route, optionally layered."""
    cell = _int(canonical_cell, "canonical cell", 0, CANONICAL_CELLS - 1)
    return _point_dict(cell, _layer(layer))


def route(canonical_cell: int, layer: int | None = None) -> str:
    """Return a relation-point route without executing or authorizing it."""
    cell = _int(canonical_cell, "canonical cell", 0, CANONICAL_CELLS - 1)
    return universe_map.route(cell, _layer(layer))


def page_directory() -> tuple[dict[str, Any], ...]:
    """Return all 256 page descriptors in ascending page order."""
    return tuple(_page_dict(index) for index in range(UNIVERSE_PAGES))


def relation_points() -> tuple[dict[str, Any], ...]:
    """Return all 32,896 relation points in canonical-cell order."""
    return tuple(_point_dict(cell) for cell in range(CANONICAL_CELLS))


def relation_point_routes(*, layer: int | None = None) -> tuple[str, ...]:
    """Return every relation-point route in canonical-cell order."""
    checked_layer = _layer(layer)
    return tuple(
        universe_map.route(cell, checked_layer)
        for cell in range(CANONICAL_CELLS)
    )


def nannet0_identity() -> dict[str, Any]:
    """Return the one NANNET0 point with its three explicit aliases."""
    value = _point_dict(NANNET0_HEAD)
    value.update({
        "head": NANNET0_HEAD,
        "page": NANNET0_PAGE,
        "ring_position": NANNET0_RING_POSITION,
        "aliases": list(NANNET0_ALIASES),
    })
    return value


def resolve_nannet0(alias: str) -> dict[str, Any]:
    """Resolve ``HW0:0``, ``page:255``, or ``ring:255`` to the same point."""
    if type(alias) is not str:
        raise UniverseGuestViewError("NANNET0 alias must be a string")
    if alias not in NANNET0_ALIASES:
        raise UniverseGuestViewError(
            "NANNET0 alias must be HW0:0, page:255, or ring:255"
        )
    value = nannet0_identity()
    value["alias"] = alias
    value["resolved"] = True
    return value


def resolve_raw(raw_address: int) -> dict[str, Any]:
    """Resolve a 16-bit double-endian address through ``MirrorRegister``."""
    raw = _int(raw_address, "raw address", 0, 0xFFFF)
    microtable = MirrorRegister.from_raw(raw)
    cell = microtable["canonical_cell"]
    canonical = universe_map.from_raw(raw)
    if canonical.canonical_cell != cell:
        raise UniverseGuestViewError(
            "MirrorRegister and universe map disagree for raw address"
        )
    value = _point_dict(cell)
    addresses = list(microtable["addresses"])
    value.update({
        "raw": raw,
        "raw_address": raw,
        "raw_address_hex": f"0x{raw:04x}",
        "raw_heads": list(microtable["heads"]),
        "canonical_address": microtable["canonical_address"],
        "addresses": addresses,
        "forward_address": addresses[0],
        "mirror_address": addresses[1],
        "orientation": microtable["orientation"],
        "topology_sha256": microtable["topology_sha256"],
        "resolved_via": "MirrorRegister.from_raw",
        "canonical_map_agrees": True,
    })
    return value


def _view_parts(view: Any) -> tuple[Any, Any, Any]:
    if not isinstance(view, dict):
        raise UniverseGuestViewError("guest view must be a mapping")
    pages = view.get("page_directory", view.get("pages"))
    points = view.get("relation_points")
    if isinstance(points, dict):
        points = points.get("points")
    routes = view.get("relation_point_routes")
    if not isinstance(pages, (list, tuple)):
        raise UniverseGuestViewError("guest view page directory is missing")
    if not isinstance(points, (list, tuple)):
        raise UniverseGuestViewError("guest view relation points are missing")
    if routes is not None and not isinstance(routes, (list, tuple)):
        raise UniverseGuestViewError("guest view relation routes are invalid")
    return pages, points, routes


def assert_full_coverage(view: Any | None = None) -> dict[str, Any]:
    """Assert the view spans every page, word, and canonical relation point."""
    if view is None:
        view = build_view()
    pages, points, routes = _view_parts(view)
    if len(pages) != UNIVERSE_PAGES:
        raise UniverseGuestViewError("page directory must contain 256 pages")
    if len(points) != CANONICAL_CELLS:
        raise UniverseGuestViewError(
            "relation points must contain all 32,896 canonical cells"
        )
    if routes is not None and len(routes) != CANONICAL_CELLS:
        raise UniverseGuestViewError("relation route list is incomplete")
    alias_pages = view.get("pages")
    if alias_pages is not None and alias_pages != pages:
        raise UniverseGuestViewError("page directory aliases disagree")

    space = view.get("address_space")
    if space is not None:
        if not isinstance(space, dict):
            raise UniverseGuestViewError("address space summary must be a mapping")
        expected_space = {
            "page_bytes": PAGE_BYTES,
            "word_bytes": WORD_BYTES,
            "page_words": PAGE_WORDS,
            "pages": UNIVERSE_PAGES,
            "words": UNIVERSE_WORDS,
            "bytes": FULL_ADDRESS_SPACE_BYTES,
            "first_page": 0,
            "last_page": UNIVERSE_PAGES - 1,
            "first_word": 0,
            "last_word": UNIVERSE_WORDS - 1,
            "first_byte": 0,
            "last_byte": FULL_ADDRESS_SPACE_BYTES - 1,
            "end_byte_exclusive": FULL_ADDRESS_SPACE_BYTES,
            "covered_bytes": FULL_ADDRESS_SPACE_BYTES,
            "uncovered_bytes": 0,
            "covers_full_8_mib": True,
        }
        for key, expected in expected_space.items():
            if space.get(key) != expected:
                raise UniverseGuestViewError(
                    f"address space summary mismatch for {key}"
                )

    for index, page in enumerate(pages):
        if type(page) is not dict:
            raise UniverseGuestViewError("page descriptor must be a mapping")
        if page.get("page") != index:
            raise UniverseGuestViewError("page directory is not contiguous")
        expected_words = index * PAGE_WORDS
        expected_bytes = expected_words * WORD_BYTES
        if page.get("offset_words") != expected_words:
            raise UniverseGuestViewError("page word offset mismatch")
        if page.get("offset_bytes") != expected_bytes:
            raise UniverseGuestViewError("page byte offset mismatch")
        if page.get("offset_end_words") != expected_words + PAGE_WORDS:
            raise UniverseGuestViewError("page word end mismatch")
        if page.get("offset_end_bytes") != expected_bytes + PAGE_BYTES:
            raise UniverseGuestViewError("page byte end mismatch")
    first_byte = pages[0].get("offset_bytes")
    end_byte = pages[-1].get("offset_end_bytes")
    if first_byte != 0 or end_byte != FULL_ADDRESS_SPACE_BYTES:
        raise UniverseGuestViewError(
            "page directory does not cover the full 8 MiB address space"
        )

    seen_pages: set[int] = set()
    for index, point in enumerate(points):
        if type(point) is not dict:
            raise UniverseGuestViewError("relation point must be a mapping")
        if point.get("canonical_cell") != index:
            raise UniverseGuestViewError(
                "relation points are not in canonical-cell order"
            )
        page_id = point.get("page")
        word = point.get("word")
        if type(page_id) is not int or not 0 <= page_id < UNIVERSE_PAGES:
            raise UniverseGuestViewError("relation point page is out of range")
        if type(word) is not int or not 0 <= word < PAGE_WORDS:
            raise UniverseGuestViewError("relation point word is out of range")
        guest_word = page_id * PAGE_WORDS + word
        if point.get("guest_word") != guest_word:
            raise UniverseGuestViewError("relation point guest word mismatch")
        if point.get("offset_words") != guest_word:
            raise UniverseGuestViewError("relation point word offset mismatch")
        if point.get("offset_bytes") != guest_word * WORD_BYTES:
            raise UniverseGuestViewError("relation point byte offset mismatch")
        if not 0 <= guest_word < UNIVERSE_WORDS:
            raise UniverseGuestViewError(
                "relation point exceeds the 8 MiB address space"
            )
        path = point.get("route")
        if type(path) is not str or not path.startswith(ROUTE_ROOT):
            raise UniverseGuestViewError("relation point route is invalid")
        if routes is not None and path != routes[index]:
            raise UniverseGuestViewError("relation point route list mismatch")
        if point.get("nannet0") is not (index == NANNET0_HEAD):
            raise UniverseGuestViewError("NANNET0 marker is inconsistent")
        seen_pages.add(page_id)

    if seen_pages != set(range(UNIVERSE_PAGES)):
        raise UniverseGuestViewError(
            "relation points do not address every universe page"
        )
    nannet0 = resolve_nannet0(NANNET0_ALIASES[0])
    if (
        nannet0["canonical_cell"] != NANNET0_HEAD
        or nannet0["page"] != NANNET0_PAGE
        or nannet0["ring_position"] != NANNET0_RING_POSITION
    ):
        raise UniverseGuestViewError("NANNET0 aliases are inconsistent")

    return {
        "schema": SCHEMA,
        "status": "green",
        "pages": len(pages),
        "words": UNIVERSE_WORDS,
        "bytes": FULL_ADDRESS_SPACE_BYTES,
        "first_byte": first_byte,
        "end_byte_exclusive": end_byte,
        "covers_full_8_mib": True,
        "relation_points": len(points),
        "fixed_heads": FIXED_POINTS,
        "mirror_pairs": PAIR_COUNT,
        "nannet0_head": NANNET0_HEAD,
        "nannet0_page": NANNET0_PAGE,
        "nannet0_ring_position": NANNET0_RING_POSITION,
        "nannet0_aliases": list(NANNET0_ALIASES),
        "host_only": True,
        "executes_kernels": False,
        "executes_math": False,
        "native_execution_claimed": False,
        "host_mapping_equals_native_execution": False,
    }


def build_view() -> dict[str, Any]:
    """Build the complete deterministic guest-view descriptor."""
    pages = list(page_directory())
    points = list(relation_points())
    routes = [point["route"] for point in points]
    view: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": VIEW_KIND,
        "host_only": True,
        "executes_kernels": False,
        "executes_math": False,
        "native_execution_verified": False,
        "native_execution_claimed": False,
        "host_mapping_equals_native_execution": False,
        "claims_relations_true": False,
        "native_required": True,
        "page_count": UNIVERSE_PAGES,
        "universe_pages": UNIVERSE_PAGES,
        "universe_words": UNIVERSE_WORDS,
        "universe_bytes": UNIVERSE_BYTES,
        "relation_point_count": CANONICAL_CELLS,
        "coverage": 1.0,
        "covers_full_8_mib": True,
        "nannet0_head": NANNET0_HEAD,
        "nannet0_page": NANNET0_PAGE,
        "nannet0_ring_position": NANNET0_RING_POSITION,
        "address_space": {
            "page_bytes": PAGE_BYTES,
            "word_bytes": WORD_BYTES,
            "page_words": PAGE_WORDS,
            "pages": UNIVERSE_PAGES,
            "words": UNIVERSE_WORDS,
            "bytes": UNIVERSE_BYTES,
            "first_page": 0,
            "last_page": UNIVERSE_PAGES - 1,
            "first_word": 0,
            "last_word": UNIVERSE_WORDS - 1,
            "first_byte": 0,
            "last_byte": UNIVERSE_BYTES - 1,
            "end_byte_exclusive": UNIVERSE_BYTES,
            "covered_bytes": UNIVERSE_BYTES,
            "uncovered_bytes": 0,
            "covers_full_8_mib": True,
        },
        "page_directory": pages,
        "pages": pages,
        "relation_points": points,
        "relation_point_routes": routes,
        "relation_point_summary": {
            "count": CANONICAL_CELLS,
            "fixed_heads": FIXED_POINTS,
            "mirror_pairs": PAIR_COUNT,
            "mapping": {
                "head_0": "NANNET0 page 255, word 0",
                "head_1_255": "page head-1, word 0",
                "mirror_pair_n": "page n % 255, word 3840 + 2*(n // 255)",
            },
        },
        "nannet0": nannet0_identity(),
        "nannet0_aliases": list(NANNET0_ALIASES),
        "route_root": ROUTE_ROOT,
        "layers": {
            "minimum": 0,
            "maximum": MAX_LAYER,
            "route_suffix": "::L{layer}",
        },
        "assertions": {
            "full_8_mib_address_space": True,
            "full_address_space_bytes": FULL_ADDRESS_SPACE_BYTES,
            "full_address_space_words": FULL_ADDRESS_SPACE_WORDS,
            "first_byte": 0,
            "end_byte_exclusive": FULL_ADDRESS_SPACE_BYTES,
            "page_directory_contiguous": True,
            "every_page_present": True,
            "every_canonical_cell_present": True,
            "every_relation_route_present": True,
            "nannet0_aliases_resolve": True,
            "coverage_assertion": (
                "page directory spans [0, 8388608) bytes (8 MiB) "
                "and all 1048576 words"
            ),
            "host_only": True,
            "kernel_execution": False,
            "native_execution": False,
            "host_mapping_equals_native_execution": False,
        },
        "non_claims": {
            "executes_kernels": False,
            "executes_math": False,
            "native_execution": False,
            "native_execution_verified": False,
            "host_mapping_equals_native_execution": False,
            "claims_relations_true": False,
            "authorizes_dispatch": False,
            "native_required": True,
        },
    }
    view["page_directory_sha256"] = universe_map.status()[
        "page_directory_sha256"
    ]
    view["page_directory_content_sha256"] = _sha256({
        "schema": SCHEMA,
        "pages": pages,
    })
    view["relation_points_sha256"] = _sha256({
        "schema": SCHEMA,
        "relation_points": points,
    })
    view["view_sha256"] = _sha256(view)
    assert_full_coverage(view)
    return view


def digest(view: Any | None = None) -> str:
    """Return the canonical SHA-256 of a view, excluding its own digest."""
    if view is None:
        view = build_view()
    if not isinstance(view, dict):
        raise UniverseGuestViewError("guest view must be a mapping")
    payload = dict(view)
    payload.pop("view_sha256", None)
    return _sha256(payload)


def to_json(view: Any | None = None, *, indent: int | None = None) -> str:
    """Serialize a view with sorted keys and deterministic separators."""
    if view is None:
        view = build_view()
    return _canonical_json(view, indent=indent)


def write_json(path: str | Path, view: Any | None = None) -> Path:
    """Write a deterministic descriptor and return its path."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(to_json(view, indent=2) + "\n", encoding="utf-8")
    return target


def status() -> dict[str, Any]:
    """Return a compact status report without materializing the full view."""
    base = universe_map.status()
    return {
        "schema": SCHEMA,
        "kind": VIEW_KIND,
        "status": "green",
        "host_only": True,
        "pages": UNIVERSE_PAGES,
        "page_bytes": PAGE_BYTES,
        "word_bytes": WORD_BYTES,
        "universe_words": UNIVERSE_WORDS,
        "universe_bytes": UNIVERSE_BYTES,
        "relation_points": CANONICAL_CELLS,
        "fixed_heads": FIXED_POINTS,
        "mirror_pairs": PAIR_COUNT,
        "nannet0_head": NANNET0_HEAD,
        "nannet0_page": NANNET0_PAGE,
        "nannet0_ring_position": NANNET0_RING_POSITION,
        "nannet0_aliases": list(NANNET0_ALIASES),
        "page_directory_sha256": base["page_directory_sha256"],
        "coverage": 1.0,
        "covers_full_8_mib": True,
        "executes_kernels": False,
        "executes_math": False,
        "claims_relations_true": False,
        "native_execution_claimed": False,
        "host_mapping_equals_native_execution": False,
    }


# Common descriptive aliases, kept as functions of the one implementation.
descriptor = build_view
guest_view = build_view
guest_view_descriptor = build_view
view_descriptor = build_view
page = page_view
point = point_view
resolve_cell = point_view
resolve_raw_address = resolve_raw
resolve_nannet0_alias = resolve_nannet0
from_raw = resolve_raw
validate = assert_full_coverage
validate_view = assert_full_coverage
view_digest = digest
view_json = to_json
dumps = to_json


__all__ = [
    "CANONICAL_CELLS",
    "FIXED_POINTS",
    "FULL_ADDRESS_SPACE_BYTES",
    "FULL_ADDRESS_SPACE_WORDS",
    "MAX_LAYER",
    "NANNET0_ALIASES",
    "NANNET0_HEAD",
    "NANNET0_PAGE",
    "NANNET0_RING_POSITION",
    "PAGE_BYTES",
    "PAGE_WORDS",
    "PAIR_COUNT",
    "REAL_HEADS",
    "ROUTE_ROOT",
    "SCHEMA",
    "UNIVERSE_BYTES",
    "UNIVERSE_PAGES",
    "UNIVERSE_WORDS",
    "VIEW_KIND",
    "WORD_BYTES",
    "UniverseGuestViewError",
    "assert_full_coverage",
    "build_view",
    "descriptor",
    "digest",
    "dumps",
    "from_raw",
    "guest_view",
    "guest_view_descriptor",
    "nannet0_identity",
    "page",
    "page_directory",
    "page_view",
    "point",
    "point_view",
    "relation_point_routes",
    "relation_points",
    "resolve_cell",
    "resolve_nannet0",
    "resolve_nannet0_alias",
    "resolve_raw",
    "resolve_raw_address",
    "route",
    "status",
    "to_json",
    "validate",
    "validate_view",
    "view_descriptor",
    "view_digest",
    "view_json",
    "write_json",
]
