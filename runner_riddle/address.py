"""Typed NaN address parser for the Bootstrap/MC0 routing grammar."""
from __future__ import annotations

from dataclasses import dataclass
import re

_ROOT = re.compile(
    r"^nan://GM(?P<gm>\d+):SC(?P<sc>\d+):MC(?P<mc>\d+):"
    r"BS(?P<bs_class>\d+):(?P<bs_node>\d+):"
    r"HW(?P<root_ns>\d+):(?P<root_head>\d+)(?P<selectors>(?:::.+)*)$"
)
_HEAD = re.compile(r"^HW(?P<namespace>\d+):(?P<heads>\d+(?:,\d+)*)$")
_OBJECT = re.compile(r"^(?P<kind>vector|hyperedge|rule|route|bin|temporal)(?P<object_id>[A-Za-z0-9_.-]+)$")


class AddressError(ValueError):
    """An address is malformed or uses an unsupported selector."""


@dataclass(frozen=True)
class HeadSelector:
    namespace: int
    heads: tuple[int, ...]


@dataclass(frozen=True)
class ObjectSelector:
    kind: str
    object_id: str


@dataclass(frozen=True)
class NanAddress:
    gm: int
    sc: int
    mc: int
    bs_class: int
    bs_node: int
    root_namespace: int
    root_head: int
    selectors: tuple[HeadSelector | ObjectSelector, ...]

    @property
    def root(self) -> str:
        return (
            f"nan://GM{self.gm}:SC{self.sc}:MC{self.mc}:"
            f"BS{self.bs_class}:{self.bs_node}:"
            f"HW{self.root_namespace}:{self.root_head}"
        )


def parse_address(value: str) -> NanAddress:
    match = _ROOT.fullmatch(value.strip())
    if not match:
        raise AddressError("invalid NaN address root or selector boundary")
    nums = {key: int(match.group(key)) for key in (
        "gm", "sc", "mc", "bs_class", "bs_node", "root_ns", "root_head"
    )}
    if any(number > 65535 for number in nums.values()):
        raise AddressError("address coordinate exceeds the v1 bound")
    selectors: list[HeadSelector | ObjectSelector] = []
    raw = match.group("selectors")
    if raw:
        for token in raw[2:].split("::"):
            head = _HEAD.fullmatch(token)
            if head:
                indices = tuple(int(item) for item in head.group("heads").split(","))
                if len(indices) > 256 or len(set(indices)) != len(indices):
                    raise AddressError("head list is duplicated or exceeds 256 entries")
                if any(index > 255 for index in indices):
                    raise AddressError("head index must be in 0..255")
                selectors.append(HeadSelector(int(head.group("namespace")), indices))
                continue
            obj = _OBJECT.fullmatch(token)
            if obj:
                selectors.append(ObjectSelector(obj.group("kind"), obj.group("object_id")))
                continue
            raise AddressError(f"unsupported selector: {token}")
    return NanAddress(
        nums["gm"], nums["sc"], nums["mc"], nums["bs_class"], nums["bs_node"],
        nums["root_ns"], nums["root_head"], tuple(selectors)
    )
