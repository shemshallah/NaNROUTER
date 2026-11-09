"""Host-only adapter from sparse WordNet HW4 rows to mirror-memory records.

The WordNet universe is the reserved hardware coordinate ``HW4:0``.  This
module maps stable synset/lemma keys onto deterministic concept IDs and one of
the 256 mirror heads, then maps relation endpoints onto canonical one-based
pair IDs.  A pair ID is computed exactly as::

    1 + a*(511-a)/2 + (b-a-1)        for 0 <= a < b <= 255

Rows are *sparse*: one synset, lemma, or typed relation per input mapping.  A
polysemous lemma remains several synset leaves; it is never collapsed into one
word record.  No row allocates a new head and no 256x256 matrix is created.

The adapter is deliberately a pure, in-process translation boundary:

* no mathematical execution and no native dispatch;
* no SQLite/database writes;
* no canonical promotion (every output is candidate evidence);
* no LLM/network fallback.

Callers receive plain copied dictionaries.  They remain responsible for any
later validation, persistence, or promotion through the canonical services.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Any

SCHEMA = "nanrouter.wordnet-mirror-adapter/1"

# The reserved WordNet universe route.  It is intentionally the persisted
# HW4 spelling requested by the WordNet allocation contract.
CANONICAL_ROUTE = "nan://GM0:SC0:MC0:BS0:0:HW4:0"
WORDNET_ROUTE = CANONICAL_ROUTE
DEFAULT_ROUTE = CANONICAL_ROUTE
ROUTE = CANONICAL_ROUTE
HW_NODE = 4
WORDNET_HW = HW_NODE

HEADS = 256
HEAD_COUNT = HEADS
PAIR_COUNT = 32_640
PAIR_ID_MIN = 1
PAIR_ID_MAX = PAIR_COUNT
PAIR_ID_VOID = 0
PAIR_ID_FORMULA = "1 + a*(511-a)/2 + (b-a-1) for 0 <= a < b <= 255"
U32_MAX = 0xFFFFFFFF

KIND_SYNSET = "synset"
KIND_LEMMA = "lemma"
LEAF_KIND = "synset_leaf"
RELATION_KIND = "relation"

# WordNet 3.x pointer symbols and their textual spellings.  Aliases are
# normalized before comparison; unknown types fail closed.
RELATION_TYPES = frozenset({
    "also_see",
    "antonym",
    "attribute",
    "cause",
    "derivationally_related",
    "domain_region",
    "domain_topic",
    "domain_usage",
    "entailment",
    "holonym",
    "hypernym",
    "hyponym",
    "in_region_domain",
    "in_topic_domain",
    "in_usage_domain",
    "instance_hypernym",
    "instance_hyponym",
    "lemma",
    "member_holonym",
    "member_meronym",
    "meronym",
    "part_holonym",
    "part_meronym",
    "participle",
    "pertainym",
    "related",
    "sense",
    "similar_to",
    "substance_holonym",
    "substance_meronym",
    "synset",
})

_RELATION_ALIASES = {
    "also": "also_see",
    "alsosee": "also_see",
    "see_also": "also_see",
    "antonymous": "antonym",
    "opposite": "antonym",
    "causes": "cause",
    "derivational": "derivationally_related",
    "derivationally_related_form": "derivationally_related",
    "derived_from": "derivationally_related",
    "domain": "domain_topic",
    "domain_category": "domain_topic",
    "region_domain": "domain_region",
    "usage_domain": "domain_usage",
    "topic_domain": "domain_topic",
    "entails": "entailment",
    "has_instance": "instance_hypernym",
    "instance": "instance_hypernym",
    "instance_of": "instance_hypernym",
    "isa": "hypernym",
    "is_a": "hypernym",
    "hypernyms": "hypernym",
    "hyponyms": "hyponym",
    "member_of_domain_region": "in_region_domain",
    "member_of_domain_topic": "in_topic_domain",
    "member_of_domain_usage": "in_usage_domain",
    "part_of": "meronym",
    "opposites": "antonym",
    "similar": "similar_to",
    "subevent": "entailment",
    "verb_group": "related",
}

_KIND_ALIASES = {
    "concept": None,
    "edge": RELATION_KIND,
    "lemma": KIND_LEMMA,
    "lemma_leaf": KIND_LEMMA,
    "lemma_sense": KIND_LEMMA,
    "relation": RELATION_KIND,
    "sense": KIND_LEMMA,
    "synset": KIND_SYNSET,
    "synset_leaf": KIND_SYNSET,
    "typed_relation": RELATION_KIND,
}

_SYNSET_SINGULAR = ("synset", "synset_key", "synset_id")
_SYNSET_PLURAL = ("synsets", "synset_keys", "synset_ids")
_LEMMA_SINGULAR = ("lemma", "lemma_key", "lemma_id")
_LEMMA_PLURAL = ("lemmas", "lemma_keys", "lemma_ids")
_SOURCE_FIELDS = ("source", "from", "subject", "source_key",
                  "source_id", "source_synset", "source_lemma")
_TARGET_FIELDS = ("target", "to", "object", "target_key",
                  "target_id", "target_synset", "target_lemma")
_RELATION_FIELDS = ("relation", "relation_type", "rel", "predicate",
                    "edge_type")
_POLARITY_FIELDS = ("polarity", "sign")
_CONFIDENCE_FIELDS = ("confidence", "confidence_q16")
_DIGEST_FIELDS = ("source_digest", "source_sha256", "row_sha256")
_EVIDENCE_FIELDS = ("evidence", "provenance", "source_evidence")
_CYCLE_FIELDS = ("cycle", "cycle_metadata")

# Domain separators prevent accidental equality between the several hashes.
_CONCEPT_DOMAIN = b"nanrouter.wordnet.concept/1\x00"
_LEAF_DOMAIN = b"nanrouter.wordnet.leaf/1\x00"
_RELATION_DOMAIN = b"nanrouter.wordnet.relation/1\x00"
_ROW_DOMAIN = b"nanrouter.wordnet.row/1\x00"
_CYCLE_DOMAIN = b"nanrouter.wordnet.cycle/1\x00"

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PAIR_STARTS = tuple(
    1 + a * (2 * HEAD_COUNT - 1 - a) // 2 for a in range(HEAD_COUNT - 1)
)


class WordNetMirrorError(ValueError):
    """A WordNet row, key, relation, or pair could not be mapped safely."""


# Conventional aliases used by neighbouring adapters.
WordNetAdapterError = WordNetMirrorError
WordNetMirrorAdapterError = WordNetMirrorError


def _integer(name: str, value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise WordNetMirrorError(
            f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _text(name: str, value: Any, *, maximum: int = 512) -> str:
    if type(value) is not str:
        raise WordNetMirrorError(f"{name} must be a string")
    value = unicodedata.normalize("NFC", value)
    if not value or value != value.strip() or len(value) > maximum:
        raise WordNetMirrorError(
            f"{name} must be a non-empty trimmed string of at most "
            f"{maximum} characters")
    if "\x00" in value:
        raise WordNetMirrorError(f"{name} must not contain NUL")
    return value


def _kind(value: Any, *, allow_none: bool = False) -> str | None:
    if type(value) is not str:
        raise WordNetMirrorError("key kind must be a string")
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized not in _KIND_ALIASES:
        raise WordNetMirrorError(f"unknown WordNet key kind: {value!r}")
    result = _KIND_ALIASES[normalized]
    if result is None and not allow_none:
        raise WordNetMirrorError("concept rows are not a synset or lemma")
    return result


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise WordNetMirrorError("value must be finite JSON data") from exc


def _json_copy(name: str, value: Any) -> Any:
    """Validate and detach one JSON value from caller-owned objects."""
    try:
        return json.loads(_canonical_json(value))
    except WordNetMirrorError as exc:
        raise WordNetMirrorError(f"{name} must be finite JSON data") from exc


def _digest(name: str, value: Any) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise WordNetMirrorError(f"{name} must be lowercase SHA-256")
    return value


def _hash_text(domain: bytes, text: str) -> str:
    return hashlib.sha256(domain + text.encode("utf-8")).hexdigest()


def stable_key(value: Any, kind: str | None = None) -> str:
    """Return the namespaced stable key for one synset or lemma.

    Accepts ``("dog", "lemma")`` and the already-namespaced
    ``"lemma:dog"`` spelling.  A bare key defaults to a synset key, which is
    the common case for WordNet relation endpoints.  The returned spelling is
    always ``synset:<key>`` or ``lemma:<key>``.
    """
    if isinstance(value, Mapping):
        if kind is not None:
            raise WordNetMirrorError("kind supplied twice for a key mapping")
        return _stable_key_from_mapping(value)
    text = _text("stable key", value)
    embedded = None
    for candidate in (KIND_SYNSET, KIND_LEMMA):
        prefix = candidate + ":"
        if text.startswith(prefix):
            embedded = candidate
            text = _text("stable key value", text[len(prefix):])
            break
    if kind is None:
        kind = embedded or KIND_SYNSET
    else:
        kind = _kind(kind)
        if embedded is not None and embedded != kind:
            raise WordNetMirrorError(
                "stable key namespace conflicts with the supplied kind")
    return f"{kind}:{text}"


def _stable_key_from_mapping(value: Mapping[str, Any]) -> str:
    found = []
    for names, kind in ((_SYNSET_SINGULAR, KIND_SYNSET),
                        (_LEMMA_SINGULAR, KIND_LEMMA)):
        for name in names:
            if name in value and value[name] is not None:
                found.append((name, stable_key(value[name], kind)))
    generic = [(name, value[name]) for name in ("key", "stable_key")
               if name in value and value[name] is not None]
    if len(found) + len(generic) == 0:
        raise WordNetMirrorError(
            "a key mapping must contain exactly one synset or lemma key")
    if len(found) + len(generic) > 1:
        raise WordNetMirrorError(
            "a key mapping must contain exactly one synset or lemma key")
    if found:
        return found[0][1]
    hint = value.get("kind", value.get("key_kind"))
    return stable_key(generic[0][1], None if hint is None else _kind(hint))


def _split_stable_key(value: str) -> tuple[str, str]:
    key = stable_key(value)
    kind, text = key.split(":", 1)
    return kind, text


def concept_id(value: Any, kind: str | None = None) -> int:
    """Map a stable synset/lemma key to a deterministic unsigned concept ID."""
    key = stable_key(value, kind)
    return int.from_bytes(
        hashlib.sha256(_CONCEPT_DOMAIN + key.encode("utf-8")).digest()[:4],
        "big",
    )


def concept_id_for_key(value: Any, kind: str | None = None) -> int:
    """Alias for :func:`concept_id`."""
    return concept_id(value, kind)


def head_for_concept(value: Any) -> int:
    """Return the deterministic 0..255 head for a concept ID."""
    value = _integer("concept_id", value, 0, U32_MAX)
    return value & (HEADS - 1)


def head_for_key(value: Any, kind: str | None = None) -> int:
    """Return the deterministic 0..255 head for a stable synset/lemma key."""
    return head_for_concept(concept_id(value, kind))


def pair_id(a: Any, b: Any) -> int:
    """Return the canonical one-based pair ID for two distinct heads.

    ``a`` and ``b`` are unordered at this boundary and are canonicalized to
    ``a < b``.  The empty/void pair sentinel is 0 and is never returned here.
    """
    a = _integer("head a", a, 0, HEAD_COUNT - 1)
    b = _integer("head b", b, 0, HEAD_COUNT - 1)
    if a == b:
        raise WordNetMirrorError(
            "a palindromic head does not identify a relation pair")
    if a > b:
        a, b = b, a
    return 1 + a * (2 * HEAD_COUNT - 1 - a) // 2 + (b - a - 1)


def pair_for_heads(a: Any, b: Any) -> int:
    """Alias for :func:`pair_id`."""
    return pair_id(a, b)


def pair_id_for_keys(source: Any, target: Any, *,
                     source_kind: str | None = None,
                     target_kind: str | None = None) -> int:
    """Map two stable keys directly to their canonical pair ID."""
    return pair_id(
        head_for_key(source, source_kind),
        head_for_key(target, target_kind),
    )


def decode_pair_id(value: Any) -> tuple[int, int]:
    """Decode a one-based pair ID into its canonical ``a < b`` heads."""
    value = _integer("pair id", value, PAIR_ID_MIN, PAIR_ID_MAX)
    low, high = 0, len(_PAIR_STARTS) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if _PAIR_STARTS[middle] <= value:
            low = middle
        else:
            high = middle - 1
    a = low
    b = a + 1 + value - _PAIR_STARTS[a]
    if not 0 <= a < b < HEAD_COUNT:
        raise WordNetMirrorError("pair id does not decode inside 0..255")
    return a, b


def pair_heads(value: Any) -> tuple[int, int]:
    """Alias for :func:`decode_pair_id`; the void pair is rejected."""
    return decode_pair_id(value)


def cycle_metadata(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Return optional metadata for the ordered cycle ``(0, i, j)``.

    Accepted spellings are ``cycle_metadata(i, j)``, ``cycle_metadata(0, i,
    j)``, one three-element sequence, or one mapping with ``root``/``i``/``j``
    keys.  Only the reserved root 0 is accepted.  The result is descriptive
    metadata only: no flux is evaluated and no cycle is executed.
    """
    if kwargs:
        unexpected = set(kwargs) - {"root", "i", "j"}
        if unexpected:
            raise WordNetMirrorError(
                f"unexpected cycle fields: {sorted(unexpected)}")
        root = kwargs.get("root", 0)
        i = kwargs.get("i")
        j = kwargs.get("j")
        if args:
            raise WordNetMirrorError("cycle coordinates supplied twice")
    elif len(args) == 1:
        value = args[0]
        if isinstance(value, Mapping):
            unexpected = set(value) - {"root", "i", "j", "cycle", "heads"}
            if unexpected:
                raise WordNetMirrorError(
                    f"unexpected cycle fields: {sorted(unexpected)}")
            root = value.get("root", 0)
            i, j = value.get("i"), value.get("j")
        elif isinstance(value, (list, tuple)):
            if len(value) != 3:
                raise WordNetMirrorError(
                    "a cycle sequence must contain exactly (0, i, j)")
            root, i, j = value
        else:
            raise WordNetMirrorError("cycle metadata must be a mapping or triple")
    elif len(args) == 2:
        root, (i, j) = 0, args
    elif len(args) == 3:
        root, i, j = args
    else:
        raise WordNetMirrorError("cycle metadata requires (i, j) or (0, i, j)")

    root = _integer("cycle root", root, 0, HEAD_COUNT - 1)
    i = _integer("cycle i", i, 0, HEAD_COUNT - 1)
    j = _integer("cycle j", j, 0, HEAD_COUNT - 1)
    if root != 0:
        raise WordNetMirrorError("only the reserved cycle root 0 is supported")
    if len({root, i, j}) != 3:
        raise WordNetMirrorError("cycle (0, i, j) requires three distinct heads")

    pair_0_i = pair_id(root, i)
    pair_i_j = pair_id(i, j)
    pair_0_j = pair_id(root, j)
    edges = [
        {"source_head": root, "target_head": i, "pair_id": pair_0_i},
        {"source_head": i, "target_head": j, "pair_id": pair_i_j},
        {"source_head": j, "target_head": root, "pair_id": pair_0_j},
    ]
    identity = {
        "schema": SCHEMA,
        "root": root,
        "i": i,
        "j": j,
        "pair_ids": [pair_0_i, pair_i_j, pair_0_j],
    }
    cycle_sha256 = _hash_text(_CYCLE_DOMAIN, _canonical_json(identity))
    return {
        "kind": "mirror-cycle/1",
        "root": root,
        "i": i,
        "j": j,
        "cycle": [root, i, j],
        "heads": [root, i, j],
        "edges": edges,
        "pair_ids": [pair_0_i, pair_i_j, pair_0_j],
        "cycle_id": cycle_sha256,
        "cycle_sha256": cycle_sha256,
        "executed": False,
        "math_execution": False,
    }


def relation_type(value: Any) -> str:
    """Normalize one WordNet relation type, failing closed on unknown types."""
    if type(value) is not str:
        raise WordNetMirrorError("relation type must be a string")
    normalized = unicodedata.normalize("NFC", value).strip().lower()
    normalized = re.sub(r"[\s-]+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    normalized = _RELATION_ALIASES.get(normalized, normalized)
    if normalized not in RELATION_TYPES:
        raise WordNetMirrorError(f"unknown WordNet relation type: {value!r}")
    return normalized


def relation_type_id(value: Any) -> int:
    """Return a stable nonzero 32-bit code for one relation type."""
    name = relation_type(value)
    code = int.from_bytes(
        hashlib.sha256(b"nanrouter.wordnet.relation-type/1\x00"
                       + name.encode("ascii")).digest()[:4],
        "big",
    )
    return code or U32_MAX


def _polarity(value: Any) -> int:
    if type(value) is str:
        normalized = value.strip().lower()
        aliases = {
            "positive": 1, "pos": 1, "+": 1, "+1": 1, "plus": 1,
            "neutral": 0, "none": 0, "zero": 0, "0": 0, "unknown": 0,
            "negative": -1, "neg": -1, "-": -1, "-1": -1, "minus": -1,
        }
        if normalized not in aliases:
            raise WordNetMirrorError("polarity must be -1, 0, or 1")
        return aliases[normalized]
    if type(value) is not int or value not in (-1, 0, 1):
        raise WordNetMirrorError("polarity must be -1, 0, or 1")
    return value


def _confidence(value: Any) -> float:
    if type(value) not in (int, float):
        raise WordNetMirrorError("confidence must be a finite number in [0,1]")
    result = float(value)
    if not 0.0 <= result <= 1.0 or result != result or result in (
            float("inf"), float("-inf")):
        raise WordNetMirrorError("confidence must be a finite number in [0,1]")
    return result


def _confidence_q16(value: Any) -> float:
    value = _integer("confidence_q16", value, 0, 65_536)
    return value / 65_536.0


def _present(row: Mapping[str, Any], names: Iterable[str]) -> list[tuple[str, Any]]:
    return [(name, row[name]) for name in names
            if name in row and row[name] is not None]


def _one_alias(row: Mapping[str, Any], names: Iterable[str]) -> tuple[str | None, Any]:
    found = _present(row, names)
    if not found:
        return None, None
    if len(found) > 1:
        first_name, first = found[0]
        for name, value in found[1:]:
            if _canonical_json(value) != _canonical_json(first):
                raise WordNetMirrorError(
                    f"ambiguous aliases {first_name!r} and {name!r}")
        return first_name, first
    return found[0]


def _row_kind(row: Mapping[str, Any]) -> str:
    name, value = _one_alias(row, ("record_type", "row_type", "kind"))
    if name is None and row.get("type") is not None:
        # ``type`` is accepted as a row kind only when it names one of the
        # known row kinds; otherwise it remains a relation-type spelling.
        candidate = row["type"]
        if type(candidate) is str:
            normalized = (candidate.strip().lower()
                          .replace("-", "_").replace(" ", "_"))
            if normalized in _KIND_ALIASES:
                name, value = "type", candidate
    if name is not None:
        if type(value) is not str:
            raise WordNetMirrorError("row kind must be a string")
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized not in _KIND_ALIASES:
            raise WordNetMirrorError(f"unknown WordNet row kind: {value!r}")
        result = _KIND_ALIASES[normalized]
        if result is None:
            raise WordNetMirrorError(
                "concept-only rows cannot emit a mirror leaf")
        return result

    has_source = bool(_present(row, _SOURCE_FIELDS))
    has_target = bool(_present(row, _TARGET_FIELDS))
    has_relation = bool(_present(row, _RELATION_FIELDS))
    if has_source or has_target or has_relation:
        if not (has_source and has_target):
            raise WordNetMirrorError(
                "relation row is incomplete: source and target are required")
        if not has_relation and row.get("type") is None:
            raise WordNetMirrorError(
                "relation row is incomplete: a relation type is required")
        return RELATION_KIND

    has_synset = bool(_present(row, _SYNSET_SINGULAR + _SYNSET_PLURAL))
    has_lemma = bool(_present(row, _LEMMA_SINGULAR + _LEMMA_PLURAL))
    if has_synset and not has_lemma:
        return KIND_SYNSET
    if has_lemma:
        return KIND_LEMMA
    raise WordNetMirrorError(
        "row must be a synset, lemma, or typed relation")


def _key_list(row: Mapping[str, Any], singular: Iterable[str],
              plural: Iterable[str], kind: str,
              *, required: bool = False) -> list[str]:
    singular_name, single = _one_alias(row, singular)
    plural_name, multiple = _one_alias(row, plural)
    if singular_name is not None and plural_name is not None:
        raise WordNetMirrorError(
            f"ambiguous singular/plural key fields {singular_name!r} and "
            f"{plural_name!r}")
    if singular_name is not None:
        values = [single]
    elif plural_name is not None:
        if isinstance(multiple, (str, bytes)) or not isinstance(
                multiple, (list, tuple)):
            raise WordNetMirrorError(f"{plural_name} must be a list of keys")
        values = list(multiple)
        if not values:
            raise WordNetMirrorError(f"{plural_name} must not be empty")
    elif required:
        raise WordNetMirrorError(f"missing {kind} key")
    else:
        return []

    result: list[str] = []
    seen = set()
    for value in values:
        key = stable_key(value, kind)
        if key in seen:
            raise WordNetMirrorError(
                f"duplicate {kind} key in one sparse row: {key}")
        seen.add(key)
        result.append(key)
    return result


def _endpoint_key(value: Any, kind: str | None, registry: Mapping[str, Any],
                  role: str) -> str:
    if isinstance(value, Mapping):
        mapping_kind = value.get("kind", value.get("key_kind"))
        if mapping_kind is not None:
            mapping_kind = _kind(mapping_kind)
            if kind is not None and mapping_kind != kind:
                raise WordNetMirrorError(
                    f"{role} key kind conflicts with its mapping")
        else:
            mapping_kind = kind
        candidates = []
        for names, candidate_kind in ((_SYNSET_SINGULAR, KIND_SYNSET),
                                      (_LEMMA_SINGULAR, KIND_LEMMA)):
            for name in names:
                if name in value and value[name] is not None:
                    if mapping_kind is not None and mapping_kind != candidate_kind:
                        raise WordNetMirrorError(
                            f"{role} mapping kind conflicts with its key")
                    candidates.append(
                        stable_key(value[name], candidate_kind))
        for name in ("key", "stable_key"):
            if name in value and value[name] is not None:
                candidates.append(stable_key(value[name], mapping_kind))
        supplied_concept = value.get("concept_id")
        if len(set(candidates)) > 1:
            raise WordNetMirrorError(
                f"{role} mapping is ambiguous: it names more than one key")
        if candidates:
            key = candidates[0]
            if supplied_concept is not None:
                expected = concept_id(key)
                if type(supplied_concept) is not int:
                    raise WordNetMirrorError(
                        f"{role} concept_id must be an integer")
                if supplied_concept != expected:
                    raise WordNetMirrorError(
                        f"{role} concept_id does not match its stable key")
            return key
        if supplied_concept is not None:
            if type(supplied_concept) is not int:
                raise WordNetMirrorError(
                    f"{role} concept_id must be an integer")
            matches = [key for key, concept in registry.items()
                       if concept["concept_id"] == supplied_concept]
            if len(matches) != 1:
                raise WordNetMirrorError(
                    f"{role} concept_id is unknown or ambiguous")
            return matches[0]
        raise WordNetMirrorError(f"{role} mapping has no stable key")

    if type(value) is int:
        matches = [key for key, concept in registry.items()
                   if concept["concept_id"] == value]
        if len(matches) != 1:
            raise WordNetMirrorError(
                f"{role} concept_id is unknown or ambiguous")
        return matches[0]

    text = _text(role, value)
    embedded = None
    for candidate in (KIND_SYNSET, KIND_LEMMA):
        prefix = candidate + ":"
        if text.startswith(prefix):
            embedded = candidate
            break
    if kind is not None:
        kind = _kind(kind)
        if embedded is not None and embedded != kind:
            raise WordNetMirrorError(
                f"{role} key namespace conflicts with its kind")
    elif embedded is not None:
        kind = embedded
    else:
        # Relations are overwhelmingly synset-to-synset.  A bare endpoint is
        # therefore the synset spelling, never a new ambiguous namespace.
        kind = KIND_SYNSET
    return stable_key(text, kind)


def _endpoint(row: Mapping[str, Any], fields: Iterable[str], role: str,
              kind_field: str | None,
              registry: Mapping[str, Any]) -> str:
    found = _present(row, fields)
    if not found:
        raise WordNetMirrorError(f"missing relation {role}")
    kind = None
    if kind_field is not None and row.get(kind_field) is not None:
        kind = _kind(row[kind_field])
    keys = []
    for name, value in found:
        field_kind = kind
        if name == f"{role}_synset":
            field_kind = KIND_SYNSET
        elif name == f"{role}_lemma":
            field_kind = KIND_LEMMA
        keys.append(_endpoint_key(value, field_kind, registry, role))
    if len(set(keys)) != 1:
        raise WordNetMirrorError(f"ambiguous relation {role} endpoints")
    return keys[0]


def _metadata(row: Mapping[str, Any]) -> tuple[str, Any, str]:
    _, digest_value = _one_alias(row, _DIGEST_FIELDS)
    if digest_value is None:
        source_digest = hashlib.sha256(
            _ROW_DOMAIN + _canonical_json(row).encode("utf-8")).hexdigest()
    else:
        source_digest = _digest("source_digest", digest_value)

    _, evidence = _one_alias(row, _EVIDENCE_FIELDS)
    if evidence is None:
        evidence = {
            "kind": "wordnet-sparse-row",
            "source_digest": source_digest,
        }
    evidence = _json_copy("evidence", evidence)
    evidence_sha256 = hashlib.sha256(
        _canonical_json(evidence).encode("utf-8")).hexdigest()
    return source_digest, evidence, evidence_sha256


def _concept(kind: str, key: str) -> dict[str, Any]:
    stable = f"{kind}:{key}"
    identifier = concept_id(stable)
    return {
        "kind": kind,
        "key": key,
        "stable_key": stable,
        "concept_id": identifier,
        "head": head_for_concept(identifier),
        "route": CANONICAL_ROUTE,
    }


def _leaf_id(synset_key: str | None, lemma_key: str | None) -> str:
    parts = [synset_key or "-", lemma_key or "-"]
    return _hash_text(_LEAF_DOMAIN, "\x00".join(parts))


def _relation_id(identity: Mapping[str, Any]) -> str:
    return _hash_text(_RELATION_DOMAIN, _canonical_json(identity))


def _candidate_flags() -> dict[str, Any]:
    return {
        "candidate_only": True,
        "canonical_promotion": False,
        "math_execution": False,
        "database_write": False,
        "llm_fallback": False,
    }


@dataclass(frozen=True)
class ConceptMapping:
    """One stable WordNet key mapped to a concept ID and mirror head."""

    kind: str
    key: str
    stable_key: str
    concept_id: int
    head: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "stable_key": self.stable_key,
            "concept_id": self.concept_id,
            "head": self.head,
            "route": CANONICAL_ROUTE,
        }


class WordNetMirrorAdapter:
    """Sparse, host-only WordNet-to-mirror-memory translation state.

    The adapter can be used as a stateless row mapper or as a small in-memory
    registry.  Its only mutable state is a dictionary of concepts, leaves, and
    emitted relation records.  Nothing is written to disk.
    """

    def __init__(self, *, cycle: Any = None,
                 include_cycle_metadata: bool = False) -> None:
        if type(include_cycle_metadata) is not bool:
            raise WordNetMirrorError("include_cycle_metadata must be a boolean")
        if cycle is None:
            self._default_cycle = None
        elif isinstance(cycle, (list, tuple)) and len(cycle) == 2:
            self._default_cycle = cycle_metadata(*cycle)
        else:
            self._default_cycle = cycle_metadata(cycle)
        self.include_cycle_metadata = include_cycle_metadata
        self._concepts: dict[str, dict[str, Any]] = {}
        self._by_concept_id: dict[int, str] = {}
        self._leaves: dict[str, dict[str, Any]] = {}
        self._relations: dict[str, dict[str, Any]] = {}

    # -- concept registry -------------------------------------------------

    def register(self, value: Any, kind: str | None = None) -> dict[str, Any]:
        """Register and return one deterministic concept mapping."""
        key = stable_key(value, kind)
        mapping = _concept(*_split_stable_key(key))
        old = self._concepts.get(mapping["stable_key"])
        if old is not None:
            if old != mapping:
                raise WordNetMirrorError("conflicting concept mapping")
            return dict(old)
        owner = self._by_concept_id.get(mapping["concept_id"])
        if owner is not None and owner != mapping["stable_key"]:
            raise WordNetMirrorError(
                "concept id collision between distinct stable keys")
        self._concepts[mapping["stable_key"]] = mapping
        self._by_concept_id[mapping["concept_id"]] = mapping["stable_key"]
        return dict(mapping)

    def register_synset(self, key: Any) -> dict[str, Any]:
        return self.register(key, KIND_SYNSET)

    def register_lemma(self, key: Any) -> dict[str, Any]:
        return self.register(key, KIND_LEMMA)

    # -- leaf construction ------------------------------------------------

    def _leaf_record(self, synset_key: str | None, lemma_key: str | None,
                     source_digest: str, evidence: Any,
                     evidence_sha256: str) -> dict[str, Any]:
        if synset_key is None and lemma_key is None:
            raise WordNetMirrorError("leaf requires a synset or lemma key")
        synset = None if synset_key is None else self.register(
            synset_key, KIND_SYNSET)
        lemma = None if lemma_key is None else self.register(
            lemma_key, KIND_LEMMA)
        primary = synset or lemma
        assert primary is not None
        leaf_id = _leaf_id(synset_key, lemma_key)
        record = {
            "schema": SCHEMA,
            "record_type": LEAF_KIND,
            "route": CANONICAL_ROUTE,
            "leaf_id": leaf_id,
            "synset_key": None if synset is None else synset["key"],
            "lemma_key": None if lemma is None else lemma["key"],
            "synset_stable_key": synset_key,
            "lemma_stable_key": lemma_key,
            "concept_id": primary["concept_id"],
            "head": primary["head"],
            "synset_concept_id": None if synset is None
                                  else synset["concept_id"],
            "synset_head": None if synset is None else synset["head"],
            "lemma_concept_id": None if lemma is None
                                 else lemma["concept_id"],
            "lemma_head": None if lemma is None else lemma["head"],
            "source_digest": source_digest,
            "evidence": _json_copy("evidence", evidence),
            "evidence_sha256": evidence_sha256,
        }
        if lemma is not None:
            # A sense is the (lemma, synset) pair.  Several synsets for one
            # lemma therefore remain several leaves with the same lemma
            # concept/head but distinct leaf and synset identities.
            record["sense_of"] = lemma["stable_key"]
            record["sense_leaf"] = synset is not None
        record.update(_candidate_flags())
        return record

    def _store_leaf(self, record: dict[str, Any]) -> dict[str, Any]:
        old = self._leaves.get(record["leaf_id"])
        if old is not None:
            if old != record:
                raise WordNetMirrorError(
                    "conflicting duplicate leaf for the same stable key")
            return dict(old)
        self._leaves[record["leaf_id"]] = record
        return dict(record)

    def map_synset(self, key: Any, *, lemma: Any = None,
                   source_digest: str | None = None,
                   evidence: Any = None) -> dict[str, Any]:
        """Map one synset, optionally attaching one lemma sense."""
        synset_key = stable_key(key, KIND_SYNSET)
        lemma_key = None if lemma is None else stable_key(lemma, KIND_LEMMA)
        row_synset = key
        row = {"synset": row_synset}
        if lemma_key is not None:
            row["lemma"] = lemma
        if source_digest is not None:
            row["source_digest"] = source_digest
        if evidence is not None:
            row["evidence"] = evidence
        digest, evidence_value, evidence_sha256 = _metadata(row)
        record = self._leaf_record(
            synset_key, lemma_key, digest, evidence_value, evidence_sha256)
        return self._store_leaf(record)

    def map_lemma(self, key: Any, synsets: Any = None, *,
                  synset: Any = None,
                  source_digest: str | None = None,
                  evidence: Any = None) -> list[dict[str, Any]]:
        """Map a lemma and each of its synset senses as separate leaves."""
        lemma_key = stable_key(key, KIND_LEMMA)
        if synsets is not None and synset is not None:
            raise WordNetMirrorError("ambiguous singular/plural synset fields")
        if synsets is None:
            values = [] if synset is None else [synset]
        elif isinstance(synsets, (str, bytes)) or not isinstance(
                synsets, (list, tuple)):
            raise WordNetMirrorError("synsets must be a list of stable keys")
        else:
            values = list(synsets)
        synset_keys = []
        seen = set()
        for value in values:
            key_value = stable_key(value, KIND_SYNSET)
            if key_value in seen:
                raise WordNetMirrorError(
                    f"duplicate synset sense for lemma: {key_value}")
            seen.add(key_value)
            synset_keys.append(key_value)

        row = {"lemma": key}
        if synsets is not None:
            row["synsets"] = list(synsets)
        if synset is not None:
            row["synset"] = synset
        if source_digest is not None:
            row["source_digest"] = source_digest
        if evidence is not None:
            row["evidence"] = evidence
        digest, evidence_value, evidence_sha256 = _metadata(row)

        records = []
        if not synset_keys:
            record = self._leaf_record(
                None, lemma_key, digest, evidence_value, evidence_sha256)
            records.append(self._store_leaf(record))
        else:
            for synset_key in synset_keys:
                record = self._leaf_record(
                    synset_key, lemma_key, digest, evidence_value,
                    evidence_sha256)
                records.append(self._store_leaf(record))
        return records

    # -- relation construction -------------------------------------------

    def map_relation(self, source: Any, target: Any, rel: Any, *,
                     source_kind: str | None = None,
                     target_kind: str | None = None,
                     polarity: Any = 0, confidence: Any = 0.0,
                     confidence_q16: Any = None,
                     source_digest: str | None = None,
                     evidence: Any = None,
                     cycle: Any = None) -> dict[str, Any]:
        """Map one typed relation to a canonical pair record.

        Missing polarity/confidence means *unassessed* (0 and 0.0); no value
        is guessed.  Missing evidence becomes a structured reference to the
        computed source-row digest.
        """
        source_key = stable_key(source, source_kind)
        target_key = stable_key(target, target_kind)
        relation_name = relation_type(rel)
        if source_key == target_key:
            raise WordNetMirrorError("a relation cannot target itself")
        polarity_value = _polarity(polarity)
        if confidence_q16 is not None:
            if confidence != 0.0:
                raise WordNetMirrorError(
                    "confidence and confidence_q16 cannot both be supplied")
            confidence_value = _confidence_q16(confidence_q16)
        else:
            confidence_value = _confidence(confidence)

        row: dict[str, Any] = {
            "source": source_key,
            "target": target_key,
            "relation": relation_name,
            "polarity": polarity_value,
            "confidence": confidence_value,
        }
        if source_digest is not None:
            row["source_digest"] = source_digest
        if evidence is not None:
            row["evidence"] = evidence
        digest, evidence_value, evidence_sha256 = _metadata(row)

        source_concept = self.register(
            source_key, _split_stable_key(source_key)[0])
        target_concept = self.register(
            target_key, _split_stable_key(target_key)[0])
        if source_concept["head"] == target_concept["head"]:
            raise WordNetMirrorError(
                "relation endpoints map to the same head; pair id is ambiguous")
        canonical_pair = pair_id(source_concept["head"], target_concept["head"])

        cycle_value = cycle
        if cycle_value is None and self._default_cycle is not None:
            cycle_value = self._default_cycle
        cycle_record = None if cycle_value is None else (
            cycle_metadata(cycle_value)
            if not isinstance(cycle_value, Mapping)
            or "cycle_id" not in cycle_value else _json_copy("cycle", cycle_value)
        )
        if cycle_record is not None and "cycle_id" not in cycle_record:
            raise WordNetMirrorError("cycle metadata is incomplete")

        identity = {
            "schema": SCHEMA,
            "route": CANONICAL_ROUTE,
            "source_stable_key": source_key,
            "target_stable_key": target_key,
            "source_concept_id": source_concept["concept_id"],
            "target_concept_id": target_concept["concept_id"],
            "source_head": source_concept["head"],
            "target_head": target_concept["head"],
            "pair_id": canonical_pair,
            "relation_type": relation_name,
            "polarity": polarity_value,
            "confidence": confidence_value,
            "source_digest": digest,
            "evidence_sha256": evidence_sha256,
            "cycle_id": None if cycle_record is None
                        else cycle_record["cycle_id"],
        }
        relation_record_id = _relation_id(identity)
        orientation = ("forward"
                       if source_concept["head"] < target_concept["head"]
                       else "mirror")
        record = {
            "schema": SCHEMA,
            "record_type": RELATION_KIND,
            "relation_id": relation_record_id,
            "route": CANONICAL_ROUTE,
            "source": {
                "key": source_concept["key"],
                "stable_key": source_key,
                "kind": source_concept["kind"],
                "concept_id": source_concept["concept_id"],
                "head": source_concept["head"],
            },
            "target": {
                "key": target_concept["key"],
                "stable_key": target_key,
                "kind": target_concept["kind"],
                "concept_id": target_concept["concept_id"],
                "head": target_concept["head"],
            },
            "source_key": source_concept["key"],
            "target_key": target_concept["key"],
            "source_stable_key": source_key,
            "target_stable_key": target_key,
            "source_kind": source_concept["kind"],
            "target_kind": target_concept["kind"],
            "source_concept_id": source_concept["concept_id"],
            "target_concept_id": target_concept["concept_id"],
            "source_head": source_concept["head"],
            "target_head": target_concept["head"],
            "heads": sorted((source_concept["head"],
                             target_concept["head"])),
            "a": min(source_concept["head"], target_concept["head"]),
            "b": max(source_concept["head"], target_concept["head"]),
            "pair_id": canonical_pair,
            "orientation": orientation,
            "relation_type": relation_name,
            "relation_type_id": relation_type_id(relation_name),
            "polarity": polarity_value,
            "confidence": confidence_value,
            "source_digest": digest,
            "evidence": _json_copy("evidence", evidence_value),
            "evidence_sha256": evidence_sha256,
        }
        if cycle_record is not None:
            record["cycle"] = _json_copy("cycle", cycle_record)
            record["cycle_id"] = cycle_record["cycle_id"]
        record.update(_candidate_flags())
        old = self._relations.get(relation_record_id)
        if old is not None:
            if old != record:
                raise WordNetMirrorError("conflicting duplicate relation record")
            return dict(old)
        self._relations[relation_record_id] = record
        return dict(record)

    # -- sparse row adaptation -------------------------------------------

    def _synset_row(self, row: Mapping[str, Any]) -> list[dict[str, Any]]:
        synsets = _key_list(
            row, _SYNSET_SINGULAR, _SYNSET_PLURAL, KIND_SYNSET,
            required=True)
        lemmas = _key_list(
            row, _LEMMA_SINGULAR, _LEMMA_PLURAL, KIND_LEMMA,
            required=False)
        if len(synsets) != 1:
            raise WordNetMirrorError(
                "a synset leaf row must name exactly one synset")
        digest, evidence, evidence_sha256 = _metadata(row)
        if not lemmas:
            return [self._store_leaf(self._leaf_record(
                synsets[0], None, digest, evidence, evidence_sha256))]
        records = []
        for lemma_key in lemmas:
            records.append(self._store_leaf(self._leaf_record(
                synsets[0], lemma_key, digest, evidence, evidence_sha256)))
        return records

    def _lemma_row(self, row: Mapping[str, Any]) -> list[dict[str, Any]]:
        lemmas = _key_list(
            row, _LEMMA_SINGULAR, _LEMMA_PLURAL, KIND_LEMMA,
            required=True)
        synsets = _key_list(
            row, _SYNSET_SINGULAR, _SYNSET_PLURAL, KIND_SYNSET,
            required=False)
        digest, evidence, evidence_sha256 = _metadata(row)
        records = []
        for lemma_key in lemmas:
            if not synsets:
                records.append(self._store_leaf(self._leaf_record(
                    None, lemma_key, digest, evidence, evidence_sha256)))
                continue
            for synset_key in synsets:
                records.append(self._store_leaf(self._leaf_record(
                    synset_key, lemma_key, digest, evidence,
                    evidence_sha256)))
        return records

    def _relation_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        source_key = _endpoint(
            row, _SOURCE_FIELDS, "source", "source_kind", self._concepts)
        target_key = _endpoint(
            row, _TARGET_FIELDS, "target", "target_kind", self._concepts)
        _, rel = _one_alias(row, _RELATION_FIELDS)
        if rel is None and row.get("type") is not None:
            rel = row["type"]
        if rel is None:
            raise WordNetMirrorError("relation row has no relation type")

        _, polarity = _one_alias(row, _POLARITY_FIELDS)
        confidence_name, confidence_value = _one_alias(
            row, _CONFIDENCE_FIELDS)
        if confidence_value is None:
            confidence = 0.0
        elif confidence_name == "confidence_q16":
            confidence = _confidence_q16(confidence_value)
        else:
            confidence = _confidence(confidence_value)

        digest, evidence, evidence_sha256 = _metadata(row)
        cycle_value = None
        for name in _CYCLE_FIELDS:
            if name not in row or row[name] is None:
                continue
            if cycle_value is not None:
                raise WordNetMirrorError("cycle metadata supplied twice")
            cycle_value = row[name]

        source_kind, _ = _split_stable_key(source_key)
        target_kind, _ = _split_stable_key(target_key)
        record = self.map_relation(
            source_key, target_key, rel,
            source_kind=source_kind, target_kind=target_kind,
            polarity=0 if polarity is None else polarity,
            confidence=confidence,
            source_digest=digest, evidence=evidence, cycle=cycle_value)
        # map_relation recomputes metadata from its synthetic row; replace the
        # row-derived values with the caller's validated row metadata.
        if record["source_digest"] != digest:
            raise WordNetMirrorError("source digest changed during adaptation")
        record["evidence"] = _json_copy("evidence", evidence)
        record["evidence_sha256"] = evidence_sha256
        return record

    def adapt_row(self, row: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
        """Adapt one sparse row into zero or more copied output records."""
        if not isinstance(row, Mapping):
            raise WordNetMirrorError("a sparse WordNet row must be a mapping")
        row = dict(row)
        kind = _row_kind(row)
        if kind == RELATION_KIND:
            records = [self._relation_row(row)]
        elif kind == KIND_SYNSET:
            records = self._synset_row(row)
        elif kind == KIND_LEMMA:
            records = self._lemma_row(row)
        else:  # pragma: no cover - _row_kind has already closed this set
            raise WordNetMirrorError("unsupported WordNet row kind")
        return tuple(_json_copy("record", record) for record in records)

    # Conventional aliases.
    map_row = adapt_row
    ingest = adapt_row

    def adapt_rows(self, rows: Iterable[Mapping[str, Any]],
                   ) -> tuple[dict[str, Any], ...]:
        """Adapt rows in order, de-duplicating exact repeated records."""
        if isinstance(rows, (str, bytes, Mapping)):
            raise WordNetMirrorError("rows must be an iterable of mappings")
        records = []
        seen = set()
        for row in rows:
            for record in self.adapt_row(row):
                identity = (record["record_type"],
                            record.get("leaf_id", record.get("relation_id")))
                if identity in seen:
                    continue
                seen.add(identity)
                records.append(record)
        return tuple(records)

    map_rows = adapt_rows
    process = adapt_rows
    adapt = adapt_rows
    map = adapt_rows

    # -- read-only views --------------------------------------------------

    def concepts(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            _json_copy("concept", self._concepts[key])
            for key in sorted(self._concepts)
        )

    def leaves(self) -> tuple[dict[str, Any], ...]:
        return tuple(_json_copy("leaf", value)
                     for value in self._leaves.values())

    def relations(self) -> tuple[dict[str, Any], ...]:
        return tuple(_json_copy("relation", value)
                     for value in self._relations.values())

    def records(self) -> tuple[dict[str, Any], ...]:
        return self.leaves() + self.relations()

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "route": CANONICAL_ROUTE,
            "concepts": list(self.concepts()),
            "leaves": list(self.leaves()),
            "relations": list(self.relations()),
            "counts": {
                "concepts": len(self._concepts),
                "leaves": len(self._leaves),
                "relations": len(self._relations),
            },
            **_candidate_flags(),
        }

    bundle = as_dict
    snapshot = as_dict

    def status(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "route": CANONICAL_ROUTE,
            "host_only": True,
            "head_space": HEAD_COUNT,
            "pair_id_min": PAIR_ID_MIN,
            "pair_id_max": PAIR_ID_MAX,
            "allocates_head_per_word": False,
            "dense_matrix_allocated": False,
            "dense_matrix_shape": None,
            "database": None,
            "writes_database": False,
            "executes_math": False,
            "canonical_promotion": False,
            "llm_fallback": False,
            "counts": {
                "concepts": len(self._concepts),
                "leaves": len(self._leaves),
                "relations": len(self._relations),
            },
        }

    def reset(self) -> None:
        """Discard in-memory mappings; no external state is touched."""
        self._concepts.clear()
        self._by_concept_id.clear()
        self._leaves.clear()
        self._relations.clear()


# Short aliases for callers that already know the HW4 context.
WordNetAdapter = WordNetMirrorAdapter
WordNetMirrorMap = WordNetMirrorAdapter
WordNetToMirrorAdapter = WordNetMirrorAdapter

canonical_pair_id = pair_id
relation_pair_id = pair_id_for_keys


def adapt_row(row: Mapping[str, Any], *,
              cycle: Any = None,
              include_cycle_metadata: bool = False,
              ) -> tuple[dict[str, Any], ...]:
    """Stateless convenience wrapper around :meth:`WordNetMirrorAdapter.adapt_row`."""
    return WordNetMirrorAdapter(
        cycle=cycle,
        include_cycle_metadata=include_cycle_metadata,
    ).adapt_row(row)


def adapt_rows(rows: Iterable[Mapping[str, Any]], *,
               cycle: Any = None,
               include_cycle_metadata: bool = False,
               ) -> tuple[dict[str, Any], ...]:
    """Stateless convenience wrapper around :meth:`WordNetMirrorAdapter.adapt_rows`."""
    return WordNetMirrorAdapter(
        cycle=cycle,
        include_cycle_metadata=include_cycle_metadata,
    ).adapt_rows(rows)


adapt_wordnet_rows = adapt_rows
map_wordnet_rows = adapt_rows
wordnet_mirror_records = adapt_rows
adapt = adapt_rows


def map_synset(key: Any, *, lemma: Any = None,
               source_digest: str | None = None,
               evidence: Any = None) -> dict[str, Any]:
    """Stateless convenience wrapper for one synset leaf."""
    return WordNetMirrorAdapter().map_synset(
        key, lemma=lemma, source_digest=source_digest, evidence=evidence)


def map_lemma(key: Any, synsets: Any = None, *, synset: Any = None,
              source_digest: str | None = None,
              evidence: Any = None) -> list[dict[str, Any]]:
    """Stateless convenience wrapper for one lemma and its senses."""
    return WordNetMirrorAdapter().map_lemma(
        key, synsets, synset=synset, source_digest=source_digest,
        evidence=evidence)


def map_relation(source: Any, target: Any, rel: Any, **kwargs: Any,
                 ) -> dict[str, Any]:
    """Stateless convenience wrapper for one typed relation."""
    if "relation" in kwargs and "rel" not in kwargs:
        rel = kwargs.pop("relation")
    return WordNetMirrorAdapter().map_relation(source, target, rel, **kwargs)


__all__ = [
    "CANONICAL_ROUTE",
    "ConceptMapping",
    "DEFAULT_ROUTE",
    "HEAD_COUNT",
    "HEADS",
    "HW_NODE",
    "KIND_LEMMA",
    "KIND_SYNSET",
    "LEAF_KIND",
    "PAIR_COUNT",
    "PAIR_ID_FORMULA",
    "PAIR_ID_MAX",
    "PAIR_ID_MIN",
    "PAIR_ID_VOID",
    "RELATION_KIND",
    "RELATION_TYPES",
    "ROUTE",
    "SCHEMA",
    "U32_MAX",
    "WORDNET_HW",
    "WORDNET_ROUTE",
    "WordNetAdapter",
    "WordNetAdapterError",
    "WordNetMirrorAdapter",
    "WordNetMirrorAdapterError",
    "WordNetMirrorError",
    "WordNetMirrorMap",
    "WordNetToMirrorAdapter",
    "adapt",
    "adapt_row",
    "adapt_rows",
    "adapt_wordnet_rows",
    "canonical_pair_id",
    "concept_id",
    "concept_id_for_key",
    "cycle_metadata",
    "decode_pair_id",
    "head_for_concept",
    "head_for_key",
    "map_lemma",
    "map_relation",
    "map_synset",
    "map_wordnet_rows",
    "pair_for_heads",
    "pair_heads",
    "pair_id",
    "pair_id_for_keys",
    "relation_pair_id",
    "relation_type",
    "relation_type_id",
    "stable_key",
    "wordnet_mirror_records",
]
