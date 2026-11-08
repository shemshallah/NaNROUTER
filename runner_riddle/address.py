"""Typed NaN address parser for the apex-layered Bootstrap/MC0 grammar.

Canonical v2 grammar (apex first, every layer separated by ``::``)::

    nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0
    nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1-255
    nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1-255:vector#1337
    nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:1:vector#1337:subrelation(42)
    nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:MP123
    nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:MP123::L4

``GM0:0`` is the global-mesh apex layer.  ``SC0:0``, ``MC0:0`` and ``BS0:0``
are the supercluster, macrocluster and bootstrap-service layers.  ``HW0:0``
is the Bootstrap hardware/network port; a following ``HW0:1-255`` selector
names the local runner-ring heads.  Object leaves use ``#`` for the object
identifier and ``:subrelation(...)`` for an optional child relation.

The pre-v2 Bootstrap spelling

    nan://GM0:SC0:MC0:BS0:0:HW0:0

is still parsed so existing persisted records can be resolved, but every
parsed address is re-emitted in the canonical apex-layered form.  A caller
must not treat the legacy spelling as a second authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

# Canonical apex-layered root.  Every layer is TYPE<namespace>:<instance> and
# layers are separated by a double colon.
_ROOT_V2 = re.compile(
    r"^nan://GM(?P<gm>\d+):(?P<gm_instance>\d+)"
    r"::SC(?P<sc>\d+):(?P<sc_instance>\d+)"
    r"::MC(?P<mc>\d+):(?P<mc_instance>\d+)"
    r"::BS(?P<bs_class>\d+):(?P<bs_node>\d+)"
    r"::HW(?P<root_ns>\d+):(?P<root_head>\d+)"
    r"(?P<selectors>(?:::|:).+)?$"
)

# The legacy Bootstrap root remains readable.  It is deliberately a separate
# pattern so a missing instance number can never be silently inferred from a
# v2 address.
_ROOT_V1 = re.compile(
    r"^nan://GM(?P<gm>\d+):SC(?P<sc>\d+):MC(?P<mc>\d+):"
    r"BS(?P<bs_class>\d+):(?P<bs_node>\d+):"
    r"HW(?P<root_ns>\d+):(?P<root_head>\d+)(?P<selectors>(?:::|:).+)?$"
)

# HW0:MP0..32639 is the mirror-pair namespace, not 32640 new heads.
# Ranges remain symbolic; no 32K-entry selector expansion.
_MP = re.compile(r"^HW(?P<namespace>\d+):MP(?P<start>\d+)(?:-(?P<end>\d+))?$")
# Conceptual L0..L9 is a bounded semantic-resolution selector, not a new VM head.
_LAYER = re.compile(r"^L(?P<layer>[0-9])$")
_HEAD = re.compile(r"^HW(?P<namespace>\d+):(?P<headspec>\d+(?:[-,]\d+)*)$")
_OBJECT = re.compile(
    r"^(?P<kind>vector|hyperedge|rule|route|bin|temporal)#"
    r"(?P<object_id>[A-Za-z0-9_.-]+)"
    r"(?::subrelation\((?P<subrelation_paren>[A-Za-z0-9_.-]+)\)"
    r"|:subrelation#(?P<subrelation_hash>[A-Za-z0-9_.-]+))?$"
)
# Pre-v2 object spelling, e.g. ``vector1337``.  Accepted for persisted-record
# compatibility only; canonical output always uses ``vector#1337``.
_OBJECT_LEGACY = re.compile(
    r"^(?P<kind>vector|hyperedge|rule|route|bin|temporal)"
    r"(?P<object_id>[A-Za-z0-9_.-]+)$"
)
# A leaf may be introduced by a single colon after a head selector.  The
# canonical form uses ``:vector#...``; ``::vector#...`` is also accepted for
# callers that treat every boundary uniformly.
_LEAF_PREFIX = re.compile(r"^:+(?P<leaf>(?:vector|hyperedge|rule|route|bin|temporal)#.+)$")
_HEAD_LEAF = re.compile(
    r"^(?P<head>HW\d+:(?:MP\d+(?:-\d+)?|\d+(?:[-,]\d+)*))"
    r"(?P<leaf>:(?:vector|hyperedge|rule|route|bin|temporal)#.+)$"
)

_MAX_COORDINATE = 65535


class AddressError(ValueError):
    """An address is malformed or uses an unsupported selector."""


@dataclass(frozen=True)
class HeadSelector:
    namespace: int
    heads: tuple[int, ...]

    @property
    def ranges(self) -> tuple[tuple[int, int], ...]:
        """Return the selector as contiguous inclusive ranges."""
        if not self.heads:
            return ()
        result: list[tuple[int, int]] = []
        start = previous = self.heads[0]
        for head in self.heads[1:]:
            if head == previous + 1:
                previous = head
                continue
            result.append((start, previous))
            start = previous = head
        result.append((start, previous))
        return tuple(result)


@dataclass(frozen=True)
class MirrorPairSelector:
    """One pair ordinal or a lazily paged interval in HW0's mirror namespace."""
    namespace: int
    start: int
    end: int

    @property
    def is_range(self) -> bool:
        return self.start != self.end

    @property
    def ordinal(self) -> int | None:
        return self.start if self.start == self.end else None


@dataclass(frozen=True)
class LayerSelector:
    """One conceptual resolution L0..L9, with no implicit proof privilege."""
    level: int


@dataclass(frozen=True)
class ObjectSelector:
    kind: str
    object_id: str
    subrelation: str | None = None


@dataclass(frozen=True)
class NanAddress:
    gm: int
    sc: int
    mc: int
    bs_class: int
    bs_node: int
    root_namespace: int
    root_head: int
    selectors: tuple[HeadSelector | MirrorPairSelector | LayerSelector | ObjectSelector, ...]
    gm_instance: int = 0
    sc_instance: int = 0
    mc_instance: int = 0

    @property
    def root(self) -> str:
        """Return the canonical apex-layered root, without selectors."""
        return (
            f"nan://GM{self.gm}:{self.gm_instance}"
            f"::SC{self.sc}:{self.sc_instance}"
            f"::MC{self.mc}:{self.mc_instance}"
            f"::BS{self.bs_class}:{self.bs_node}"
            f"::HW{self.root_namespace}:{self.root_head}"
        )

    @property
    def canonical(self) -> str:
        """Alias for :attr:`root`; the canonical v2 root."""
        return self.root

    @property
    def legacy_root(self) -> str:
        """Return the pre-v2 root spelling for migration/compatibility only."""
        return (
            f"nan://GM{self.gm}:SC{self.sc}:MC{self.mc}:"
            f"BS{self.bs_class}:{self.bs_node}:"
            f"HW{self.root_namespace}:{self.root_head}"
        )

    @property
    def head_selectors(self) -> tuple[HeadSelector, ...]:
        return tuple(
            item for item in self.selectors if isinstance(item, HeadSelector)
        )

    @property
    def mirror_pair_selectors(self) -> tuple[MirrorPairSelector, ...]:
        return tuple(item for item in self.selectors
                     if isinstance(item, MirrorPairSelector))

    @property
    def layer_selectors(self) -> tuple[LayerSelector, ...]:
        return tuple(item for item in self.selectors if isinstance(item, LayerSelector))

    @property
    def object_selectors(self) -> tuple[ObjectSelector, ...]:
        return tuple(
            item for item in self.selectors if isinstance(item, ObjectSelector)
        )

    def canonical_with_selectors(self) -> str:
        """Render this full address in canonical v2 form."""
        rendered = self.root
        for selector in self.selectors:
            if isinstance(selector, HeadSelector):
                rendered += "::" + _render_heads(selector)
                continue
            if isinstance(selector, MirrorPairSelector):
                rendered += f"::HW{selector.namespace}:MP{selector.start}"
                if selector.is_range:
                    rendered += f"-{selector.end}"
                continue
            if isinstance(selector, LayerSelector):
                rendered += f"::L{selector.level}"
                continue
            rendered += f":{selector.kind}#{selector.object_id}"
            if selector.subrelation is not None:
                rendered += f":subrelation({selector.subrelation})"
        return rendered


def _render_heads(selector: HeadSelector) -> str:
    """Render a head selector compactly, preserving contiguous ranges."""
    rendered = [
        str(start) if start == end else f"{start}-{end}"
        for start, end in selector.ranges
    ]
    return f"HW{selector.namespace}:" + ",".join(rendered)


def _check_coordinate(name: str, value: int, maximum: int) -> int:
    if value < 0 or value > maximum:
        raise AddressError(f"{name} must be in 0..{maximum}")
    return value


def _expand_heads(spec: str) -> tuple[int, ...]:
    heads: list[int] = []
    for item in spec.split(","):
        if not item:
            raise AddressError("empty head selector item")
        if "-" in item:
            bounds = item.split("-")
            if len(bounds) != 2 or not bounds[0] or not bounds[1]:
                raise AddressError("head range must be lower-upper")
            lower, upper = int(bounds[0]), int(bounds[1])
            if lower > upper:
                raise AddressError("head range lower bound exceeds upper bound")
            heads.extend(range(lower, upper + 1))
        else:
            heads.append(int(item))
    if len(heads) > 256:
        raise AddressError("head selector exceeds 256 entries")
    if len(set(heads)) != len(heads):
        raise AddressError("head list is duplicated")
    if any(head < 0 or head > 255 for head in heads):
        raise AddressError("head index must be in 0..255")
    return tuple(heads)


def _parse_selector(token: str) -> HeadSelector | MirrorPairSelector | LayerSelector | ObjectSelector:
    layer = _LAYER.fullmatch(token)
    if layer:
        return LayerSelector(int(layer.group("layer")))
    mp = _MP.fullmatch(token)
    if mp:
        namespace = _check_coordinate("MP namespace", int(mp.group("namespace")), 255)
        if namespace != 0:
            raise AddressError("mirror pairs belong to HW0 only")
        start = int(mp.group("start"))
        end = int(mp.group("end") or start)
        if not (0 <= start <= end < 32640):
            raise AddressError("mirror pair ordinal must be 0..32639, with increasing range")
        return MirrorPairSelector(namespace, start, end)
    head = _HEAD.fullmatch(token)
    if head:
        namespace = _check_coordinate(
            "HW namespace", int(head.group("namespace")), 255
        )
        return HeadSelector(namespace, _expand_heads(head.group("headspec")))
    leaf = _LEAF_PREFIX.fullmatch(token)
    if leaf:
        token = leaf.group("leaf")
    obj = _OBJECT.fullmatch(token)
    if obj:
        subrelation = obj.group("subrelation_paren") or obj.group(
            "subrelation_hash"
        )
        return ObjectSelector(
            obj.group("kind"), obj.group("object_id"), subrelation
        )
    legacy = _OBJECT_LEGACY.fullmatch(token)
    if legacy:
        return ObjectSelector(
            legacy.group("kind"), legacy.group("object_id"), None
        )
    raise AddressError(f"unsupported selector: {token}")


def _parse_selectors(raw: str) -> tuple[HeadSelector | MirrorPairSelector | LayerSelector | ObjectSelector, ...]:
    if not raw:
        return ()
    # ``::`` separates layers/selectors; a single ``:`` introduces a leaf.
    if raw.startswith("::"):
        result: list[HeadSelector | MirrorPairSelector | LayerSelector | ObjectSelector] = []
        for chunk in raw[2:].split("::"):
            if not chunk:
                raise AddressError("empty address selector")
            leaf = _LEAF_PREFIX.fullmatch(chunk)
            if leaf:
                result.append(_parse_selector(leaf.group("leaf")))
                continue
            head_leaf = _HEAD_LEAF.fullmatch(chunk)
            if head_leaf:
                result.append(_parse_selector(head_leaf.group("head")))
                result.append(_parse_selector(head_leaf.group("leaf")[1:]))
                continue
            result.append(_parse_selector(chunk))
        return tuple(result)
    leaf = _LEAF_PREFIX.fullmatch(raw)
    if leaf:
        return (_parse_selector(leaf.group("leaf")),)
    raise AddressError("invalid selector boundary")


def parse_address(value: str) -> NanAddress:
    """Parse a canonical v2 or legacy v1 NaN address.

    The returned object always emits :attr:`NanAddress.root` in canonical v2
    form.  Legacy v1 input is accepted only for migration and persisted-record
    compatibility.
    """
    text = value.strip()
    if text.startswith("math://"):
        raise AddressError(
            "route_context_mismatch: math:// is a linker context, not a router address"
        )
    match = _ROOT_V2.fullmatch(text)
    syntax = "v2"
    if match is None:
        match = _ROOT_V1.fullmatch(text)
        syntax = "v1"
    if match is None:
        raise AddressError("invalid NaN address root or selector boundary")
    groups = match.groupdict()
    if syntax == "v2":
        gm_instance = int(groups["gm_instance"])
        sc_instance = int(groups["sc_instance"])
        mc_instance = int(groups["mc_instance"])
    else:
        gm_instance = sc_instance = mc_instance = 0
    values = {
        "gm": int(groups["gm"]),
        "sc": int(groups["sc"]),
        "mc": int(groups["mc"]),
        "bs_class": int(groups["bs_class"]),
        "bs_node": int(groups["bs_node"]),
        "root_ns": int(groups["root_ns"]),
        "root_head": int(groups["root_head"]),
    }
    for name, number in (
        ("GM", values["gm"]),
        ("SC", values["sc"]),
        ("MC", values["mc"]),
        ("BS class", values["bs_class"]),
        ("BS node", values["bs_node"]),
        ("GM instance", gm_instance),
        ("SC instance", sc_instance),
        ("MC instance", mc_instance),
    ):
        _check_coordinate(name, number, _MAX_COORDINATE)
    _check_coordinate("root HW namespace", values["root_ns"], 255)
    _check_coordinate("root HW head", values["root_head"], 255)
    parsed_selectors = _parse_selectors(groups["selectors"])
    # Exactly one layer selector after an actual head/MP coordinate.
    # A math:// leaf is never inferred from Lx alone.
    layers = [i for i, v in enumerate(parsed_selectors)
              if isinstance(v, LayerSelector)]
    if layers:
        if len(layers) != 1 or layers[0] == 0 or (
                not isinstance(parsed_selectors[layers[0] - 1],
                               (HeadSelector, MirrorPairSelector))):
            raise AddressError("L0..L9 must follow one HW head or MP selector")
    return NanAddress(
        values["gm"],
        values["sc"],
        values["mc"],
        values["bs_class"],
        values["bs_node"],
        values["root_ns"],
        values["root_head"],
        parsed_selectors,
        gm_instance,
        sc_instance,
        mc_instance,
    )
