"""Generation-chained, signed route cache and micro-route compiler.

Candidate learning is intentionally separate from committed routing. The
cache writer requires an explicit route-commit capability and a generation CAS.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from pathlib import Path
import tempfile
from typing import Any

from .address import HeadSelector, NanAddress, ObjectSelector, parse_address

class RouteError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sign(value: Any, key: bytes) -> str:
    return hmac.new(key, _canonical(value), hashlib.sha256).hexdigest()


class MasterRouteCache:
    def __init__(self, document: dict[str, Any], key: bytes):
        self.key = key
        self.document = document
        self.verify()

    @classmethod
    def empty(cls, network_id: str, key: bytes) -> "MasterRouteCache":
        core = {
            "schema": "nanrouter.master-cache.v1",
            "network_id": network_id,
            "generation": 0,
            "previous_digest": None,
            "routes": [],
            "head_associations": [],
            "object_associations": [],
        }
        return cls({**core, "cache_digest": _digest(core), "signature": _sign(core, key)}, key)

    @classmethod
    def load(cls, path: str | Path, key: bytes) -> "MasterRouteCache":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), key)

    def verify(self) -> None:
        doc = self.document
        if doc.get("schema") != "nanrouter.master-cache.v1":
            raise RouteError("unsupported cache schema")
        core = {k: v for k, v in doc.items() if k not in ("cache_digest", "signature")}
        if not hmac.compare_digest(str(doc.get("cache_digest", "")), _digest(core)):
            raise RouteError("master cache digest mismatch")
        if not hmac.compare_digest(str(doc.get("signature", "")), _sign(core, self.key)):
            raise RouteError("master cache signature mismatch")
        if not isinstance(doc.get("routes"), list):
            raise RouteError("routes must be an array")
        if not isinstance(doc.get("head_associations"), list):
            raise RouteError("head_associations must be an array")
        if not isinstance(doc.get("object_associations"), list):
            raise RouteError("object_associations must be an array")
        head_keys = [r.get("head_key") for r in doc["head_associations"]]
        object_keys = [str(r.get("kind")) + ":" + str(r.get("object_id")) for r in doc["object_associations"]]
        if len(head_keys) != len(set(head_keys)) or len(object_keys) != len(set(object_keys)):
            raise RouteError("duplicate committed address association")
        ids = [r.get("route_id") for r in doc["routes"]]
        if len(ids) != len(set(ids)):
            raise RouteError("duplicate route_id in committed cache")

    @property
    def generation(self) -> int:
        return int(self.document["generation"])

    @property
    def digest(self) -> str:
        return str(self.document["cache_digest"])

    def propose(self, record: dict[str, Any]) -> dict[str, Any]:
        """Return a candidate only; never mutates the committed cache."""
        candidate = dict(record)
        candidate["state"] = "candidate"
        candidate["base_generation"] = self.generation
        candidate["generation"] = self.generation + 1
        return candidate

    def commit(self, candidate: dict[str, Any], *, expected_generation: int,
               capabilities: set[str]) -> dict[str, Any]:
        if "nannet.route.commit" not in capabilities:
            raise RouteError("route commit capability required")
        if expected_generation != self.generation:
            raise RouteError("stale cache generation")
        if candidate.get("base_generation") != self.generation:
            raise RouteError("candidate was learned against a stale generation")
        if candidate.get("state") != "candidate":
            raise RouteError("only candidate routes can be committed")
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get("source_hash", ""))):
            raise RouteError("route source_hash must be lowercase SHA-256 hex")
        if not re.fullmatch(r"[0-9a-f]{64}", str(candidate.get("acl_digest", ""))):
            raise RouteError("route acl_digest must be lowercase SHA-256 hex")
        if candidate.get("permanence") != "permanent":
            raise RouteError("the BS0 root route must have permanent identity")
        if not candidate.get("source_ref") or not candidate.get("target_ref"):
            raise RouteError("route source_ref and target_ref are required")
        target_head = candidate.get("target_head")
        if not isinstance(target_head, dict):
            raise RouteError("route requires a typed target_head association")
        try:
            parsed_root = parse_address(str(candidate.get("canonical_address", "")))
        except ValueError as exc:
            raise RouteError("candidate canonical_address is invalid") from exc
        if parsed_root.selectors:
            raise RouteError("committed route canonical_address must be a root address without selectors")
        if (not target_head.get("universe_id") or not target_head.get("head_ref")
                or target_head.get("permanence") != candidate.get("permanence")
                or target_head.get("head_ref") != candidate.get("target_ref")
                or int(target_head.get("namespace", -1)) != parsed_root.root_namespace
                or int(target_head.get("head_index", -1)) != parsed_root.root_head
                or not 0 <= int(target_head.get("node_point", -1)) <= 255):
            raise RouteError("target_head association is incomplete or inconsistent")
        routes = list(self.document["routes"])
        if any(r.get("route_id") == candidate.get("route_id") for r in routes):
            raise RouteError("route_id already exists")
        if any(r.get("canonical_address") == candidate.get("canonical_address")
               and r.get("state") == "committed" for r in routes):
            raise RouteError("canonical address already has a committed route")
        committed = dict(candidate, state="committed", generation=self.generation + 1)
        core = {
            "schema": "nanrouter.master-cache.v1",
            "network_id": self.document["network_id"],
            "generation": self.generation + 1,
            "previous_digest": self.digest,
            "routes": routes + [committed],
            "head_associations": list(self.document["head_associations"]),
            "object_associations": list(self.document["object_associations"]),
        }
        self.document = {**core, "cache_digest": _digest(core), "signature": _sign(core, self.key)}
        self.verify()
        return committed

    def _publish_associations(self, *, head_associations: list[dict[str, Any]],
                               object_associations: list[dict[str, Any]]) -> None:
        core = {
            "schema": "nanrouter.master-cache.v1",
            "network_id": self.document["network_id"],
            "generation": self.generation + 1,
            "previous_digest": self.digest,
            "routes": list(self.document["routes"]),
            "head_associations": head_associations,
            "object_associations": object_associations,
        }
        self.document = {**core, "cache_digest": _digest(core), "signature": _sign(core, self.key)}
        self.verify()

    def register_head_association(self, record: dict[str, Any], *,
                                  expected_generation: int,
                                  capabilities: set[str]) -> dict[str, Any]:
        if "universe.atlas.commit" not in capabilities:
            raise RouteError("universe atlas commit capability required")
        if expected_generation != self.generation or record.get("base_generation") != self.generation:
            raise RouteError("stale head-association generation")
        namespace = int(record.get("namespace", -1))
        head_index = int(record.get("head_index", -1))
        if not 0 <= namespace <= 255 or not 0 <= head_index <= 255:
            raise RouteError("head association coordinate outside 0..255")
        key = f"HW{namespace}:{head_index}"
        if not record.get("universe_id") or not record.get("head_ref"):
            raise RouteError("head association requires universe_id and head_ref")
        if not 0 <= int(record.get("node_point", -1)) <= 255:
            raise RouteError("head association node point outside 0..255")
        if record.get("permanence") not in ("permanent", "ephemeral"):
            raise RouteError("invalid head permanence")
        lease_until = record.get("lease_until_tick")
        if record.get("permanence") == "permanent" and lease_until is not None:
            raise RouteError("permanent head associations cannot carry an expiry lease")
        if record.get("permanence") == "ephemeral" and (
            not isinstance(lease_until, int) or lease_until <= int(record.get("nanclock_tick", -1))
        ):
            raise RouteError("ephemeral head associations require a future lease expiry")
        for field in ("source_hash", "acl_digest"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(record.get(field, ""))):
                raise RouteError(f"head association {field} must be SHA-256 hex")
        if not record.get("learner_id") or int(record.get("nanclock_tick", -1)) < 0:
            raise RouteError("head association provenance is incomplete")
        if any(item.get("head_key") == key for item in self.document["head_associations"]):
            raise RouteError("head association already committed; permanent identity cannot be overwritten")
        for route in self.document["routes"]:
            if route.get("state") != "committed":
                continue
            root = parse_address(route["canonical_address"])
            if key == f"HW{root.root_namespace}:{root.root_head}":
                raise RouteError("a committed route root head cannot be reassigned")
        committed = dict(record, head_key=key, generation=self.generation + 1, state="committed")
        self._publish_associations(
            head_associations=list(self.document["head_associations"]) + [committed],
            object_associations=list(self.document["object_associations"]),
        )
        return committed

    def register_object_association(self, record: dict[str, Any], *,
                                    expected_generation: int,
                                    capabilities: set[str]) -> dict[str, Any]:
        if "universe.atlas.commit" not in capabilities:
            raise RouteError("universe atlas commit capability required")
        if expected_generation != self.generation or record.get("base_generation") != self.generation:
            raise RouteError("stale object-association generation")
        kind, object_id = str(record.get("kind", "")), str(record.get("object_id", ""))
        if kind not in ("vector", "hyperedge", "rule", "route", "bin", "temporal") or not object_id:
            raise RouteError("invalid typed object association key")
        if not record.get("association_ref") or not record.get("learner_id"):
            raise RouteError("object association reference and learner are required")
        for field in ("source_hash", "acl_digest"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(record.get(field, ""))):
                raise RouteError(f"object association {field} must be SHA-256 hex")
        key = kind + ":" + object_id
        if any(str(item.get("kind")) + ":" + str(item.get("object_id")) == key
               for item in self.document["object_associations"]):
            raise RouteError("typed object association already committed")
        committed = dict(record, generation=self.generation + 1, state="committed")
        self._publish_associations(
            head_associations=list(self.document["head_associations"]),
            object_associations=list(self.document["object_associations"]) + [committed],
        )
        return committed

    def save_atomic(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _canonical(self.document) + b"\n"
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @classmethod
    def commit_atomic(cls, path: str | Path, *, key: bytes, network_id: str,
                      candidate: dict[str, Any], expected_generation: int,
                      capabilities: set[str]) -> tuple["MasterRouteCache", dict[str, Any]]:
        """Serialize competing writers with an OS lock and generation CAS."""
        import fcntl

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock_path = str(target) + ".lock"
        with open(lock_path, "a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            cache = cls.load(target, key) if target.exists() else cls.empty(network_id, key)
            committed = cache.commit(
                candidate, expected_generation=expected_generation,
                capabilities=capabilities
            )
            cache.save_atomic(target)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            return cache, committed

    def resolve(self, address: str, *, now_tick: int | None = None) -> dict[str, Any]:
        parsed = parse_address(address)
        head_refs = {item["head_key"]: item for item in self.document["head_associations"]
                     if item.get("state") == "committed"}
        for committed_route in self.document["routes"]:
            if committed_route.get("state") == "committed":
                root_address = parse_address(committed_route["canonical_address"])
                root_key = f"HW{root_address.root_namespace}:{root_address.root_head}"
                head_refs[root_key] = committed_route["target_head"]
        object_refs = {str(item["kind"]) + ":" + str(item["object_id"]): item
                       for item in self.document["object_associations"]
                       if item.get("state") == "committed"}
        root = parsed.root
        route = next((r for r in self.document["routes"]
                      if r.get("canonical_address") == root and r.get("state") == "committed"), None)
        if route is None:
            raise RouteError("root route is not committed in the master cache")
        resolved_heads: list[dict[str, Any]] = []
        root_head = route.get("target_head")
        if not isinstance(root_head, dict):
            raise RouteError("committed root route is missing its typed target_head")
        if root_head.get("permanence") != "permanent":
            raise RouteError("BS0 root head must remain permanently attached")
        if not root_head.get("head_ref"):
            raise RouteError("root head reference is missing")
        resolved_heads.append({
            "namespace": parsed.root_namespace,
            "universe_id": root_head["universe_id"],
            "node_point": root_head["node_point"],
            "head_index": root_head["head_index"],
            "permanence": root_head["permanence"],
            "head_ref": root_head["head_ref"],
        })
        resolved_objects: list[dict[str, Any]] = []
        for selector in parsed.selectors:
            if isinstance(selector, HeadSelector):
                for index in selector.heads:
                    key = f"HW{selector.namespace}:{index}"
                    record = head_refs.get(key)
                    if record is None:
                        raise RouteError(f"unregistered head selector: {key}")
                    if record.get("permanence") not in ("permanent", "ephemeral"):
                        raise RouteError(f"invalid permanence for head selector: {key}")
                    if record.get("permanence") == "ephemeral":
                        lease_until = record.get("lease_until_tick")
                        if now_tick is None or not isinstance(lease_until, int) or now_tick >= lease_until:
                            raise RouteError(f"ephemeral head lease expired or current tick missing: {key}")
                    if not record.get("head_ref") or not record.get("universe_id"):
                        raise RouteError(f"incomplete head association: {key}")
                    resolved_heads.append({
                        "namespace": selector.namespace,
                        "universe_id": record["universe_id"],
                        "node_point": record["node_point"],
                        "head_index": record["head_index"],
                        "permanence": record["permanence"],
                        "head_ref": record["head_ref"],
                    })
            elif isinstance(selector, ObjectSelector):
                key = f"{selector.kind}:{selector.object_id}"
                record = object_refs.get(key)
                if record is None:
                    raise RouteError(f"unregistered object selector: {key}")
                if record.get("kind") != selector.kind or str(record.get("object_id")) != selector.object_id:
                    raise RouteError(f"typed object association mismatch: {key}")
                if not record.get("association_ref"):
                    raise RouteError(f"object association reference missing: {key}")
                resolved_objects.append({
                    "kind": record["kind"],
                    "object_id": str(record["object_id"]),
                    "association_ref": record["association_ref"],
                })
        packet = {
            "schema": "nanrouter.micro-route.v1",
            "cache_generation": self.generation,
            "route_id": route["route_id"],
            "source_address": address,
            "resolved_heads": resolved_heads,
            "object_refs": resolved_objects,
            "bridge_profile": route.get("bridge_profile", "local-only"),
            "acl_digest": route["acl_digest"],
        }
        packet["packet_digest"] = _digest(packet)
        packet["signature"] = _sign(packet, self.key)
        return packet
