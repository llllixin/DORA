"""A01 ontology shape and cross-record contracts; no database/network dependency."""
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from app.rag.contracts import KNOWLEDGE_ROOT, PROJECT_ROOT, RagContractError

# Project physical storage, not an inferred accounting definition.
BINDINGS = {
    "metric.margin": ("margin", "全国", "%", "fixed"),
    "metric.returns": ("returns", None, "%", "store_or_all_rows"),
    "metric.orders": ("orders", "全国", None, "fixed_with_east_view"),
    "metric.revenue": ("revenue", "全国", "千元", "fixed"),
    "metric.aov": ("aov", "全国", "元", "fixed"),
    "metric.east_orders": ("east_orders", "华东", None, "fixed"),
    "metric.new_sku": ("new_sku", "全区域", None, "fixed"),
    "metric.high_value": ("high_value", "全国", "%", "fixed"),
    "metric.supplier_price": ("supplier_price", None, "元", "supplier_or_all_rows"),
}
RELATIONS = {
    "related_to": (["Metric"], ["Metric"], "concept", True, True, True),
    "slice_of": (["Metric"], ["Metric"], "concept", False, True, False),
    "describes_collection": (["Metric"], ["Collection"], "concept", False, False, False),
    "uses_procedure": (["Procedure"], ["Procedure"], "concept", False, True, False),
    "references_metric": (["Procedure"], ["Metric"], "concept", False, False, False),
    "applies_to": (["Rule"], ["Metric"], "concept", False, False, False),
    "has_region": (["Metric", "Collection"], ["Region"], "concept", False, False, False),
    "has_dimension": (["Metric", "Collection"], ["Dimension"], "concept", False, False, False),
    "observed_as": (["Metric"], ["MetricObservation"], "instance", False, False, False),
    "produced_occurrence": (["Rule"], ["InsightOccurrence"], "instance", False, False, False),
    "supported_by": (["InsightOccurrence"], ["Snapshot"], "instance", False, False, False),
    "monitors": (["WatchTarget"], ["Metric"], "instance", False, False, False),
    "emitted": (["WatchTarget"], ["WatchEvent"], "instance", False, False, False),
    "opened_from": (["ActionCase"], ["InsightOccurrence"], "instance", False, False, False),
    "lesson_from": (["Lesson"], ["ActionCase"], "instance", False, False, False),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RagContractError(message)


def content_hash(raw: Any) -> str:
    value = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _shape(value: Any, schema: dict, path: str = "ontology") -> None:
    """Execute only the self-contained JSON Schema keywords used by v2.

    Unknown keywords fail closed; this is not a general JSON Schema engine.
    """
    known = {"$schema", "title", "type", "const", "enum", "anyOf", "properties", "required",
             "additionalProperties", "items", "minItems", "uniqueItems", "minLength", "pattern"}
    require(not (set(schema) - known), f"{path}: unsupported schema keyword")
    if "anyOf" in schema:
        for alternative in schema["anyOf"]:
            try:
                _shape(value, alternative, path)
                return
            except RagContractError:
                pass
        raise RagContractError(f"{path}: does not match any allowed shape")
    matches = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "null": value is None,
        "boolean": type(value) is bool, "integer": type(value) is int,
        "number": type(value) in (int, float),
    }
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        require(all(t in matches for t in types), f"{path}: unknown schema type")
        require(any(matches[t] for t in types), f"{path}: invalid type")
    if "const" in schema:
        require(content_hash(value) == content_hash(schema["const"]), f"{path}: invalid constant")
    if "enum" in schema:
        require(any(content_hash(value) == content_hash(v) for v in schema["enum"]), f"{path}: invalid enum")
    if isinstance(value, str):
        require(len(value.strip()) >= schema.get("minLength", 0), f"{path}: empty string")
        if "pattern" in schema:
            require(bool(re.search(schema["pattern"], value)), f"{path}: invalid pattern")
    if isinstance(value, dict):
        require(set(schema.get("required", [])) <= set(value), f"{path}: required fields missing")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(set(value) <= set(properties), f"{path}: unknown fields")
        for key in value.keys() & properties.keys():
            _shape(value[key], properties[key], f"{path}.{key}")
    if isinstance(value, list):
        require(len(value) >= schema.get("minItems", 0), f"{path}: empty array")
        if schema.get("uniqueItems"):
            require(len({content_hash(v) for v in value}) == len(value), f"{path}: duplicate values")
        if "items" in schema:
            for index, item in enumerate(value):
                _shape(item, schema["items"], f"{path}[{index}]")


def _index(rows: list[dict], name: str) -> dict[str, dict]:
    out = {row["id"]: row for row in rows}
    require(len(out) == len(rows), f"{name}: duplicate id")
    require(all(re.fullmatch(r"[a-z][a-z0-9._-]*", key) for key in out), f"{name}: invalid id")
    return out


def _sources(refs: list[str]) -> None:
    for ref in refs:
        if ref.startswith("https://"):
            continue  # Declaration only; never fetch external evidence.
        path = (PROJECT_ROOT / ref).resolve()
        require(path.is_relative_to(PROJECT_ROOT) and path.is_file(), f"unknown sourceRef: {ref}")


def validate_ontology(raw: Any, *, allow_candidate: bool = False) -> dict:
    try:
        schema = json.loads((KNOWLEDGE_ROOT / "schema/ontology.schema.json").read_text(encoding="utf-8"))
        _shape(raw, schema)
        allowed = {"reviewed", "candidate_for_review"} if allow_candidate else {"reviewed"}
        require(raw["reviewStatus"] in allowed, "ontology is not a reviewed publication")
        concepts = _index(raw["concepts"], "concepts")
        require(set(raw["legacyConceptIds"]) <= set(concepts), "legacy concept id missing")
        aliases = {}
        for cid, concept in concepts.items():
            for alias in [concept["name"], *concept["aliases"]]:
                key = alias.strip().casefold()
                require(key not in aliases, f"alias conflict: {alias}")
                aliases[key] = cid
            _sources(concept["sourceRefs"])
            binding = concept["metricBinding"]
            if binding is not None:
                require(concept["type"] == "Metric" and cid in BINDINGS, f"unapproved metric binding: {cid}")
                actual = (binding["metricKey"], binding["dimension"], binding["sourceUnit"], binding["dimensionPolicy"])
                require(actual == BINDINGS[cid], f"physical binding mismatch: {cid}")
        catalog = _index(raw["relationTypes"], "relationTypes")
        require(set(catalog) == set(RELATIONS), "unknown or incomplete relation catalog")
        for rid, relation in catalog.items():
            policy = relation["queryExpansion"]
            actual = (relation["domain"], relation["range"], relation["layer"], relation["symmetric"], policy["fromMatched"], policy["toMatched"])
            require(actual == RELATIONS[rid], f"relation direction/policy mismatch: {rid}")
        pairs = set()
        for view in raw["regionViews"]:
            base, child, region = view["baseConceptId"], view["viewConceptId"], view["regionId"]
            require(base in concepts and child in concepts and region in concepts, "unknown region view endpoint")
            require(concepts[base]["type"] == concepts[child]["type"] == "Metric" and concepts[region]["type"] == "Region", "invalid region view type")
            binding = concepts[child]["metricBinding"]
            require(binding is not None and binding["dimension"] == concepts[region]["name"], "region view binding mismatch")
            require((child, base) not in pairs, "duplicate region view")
            pairs.add((child, base))
        edges = _index(raw["relations"], "relations")
        triples = set()
        for edge in edges.values():
            source, target, kind = edge["from"], edge["to"], edge["type"]
            require(source in concepts and target in concepts and kind in catalog, "unknown relation endpoint/type")
            relation = catalog[kind]
            require(relation["layer"] == "concept", "instance edge in concept ontology")
            require(concepts[source]["type"] in relation["domain"] and concepts[target]["type"] in relation["range"], "relation endpoint type mismatch")
            if kind == "slice_of":
                require((source, target) in pairs, "slice_of direction disagrees with region view")
            triple = (min(source, target), kind, max(source, target)) if relation["symmetric"] else (source, kind, target)
            require(triple not in triples and source != target, "duplicate/self relation")
            triples.add(triple)
            _sources(edge["sourceRefs"])
        _index(raw["blockedTerms"], "blockedTerms")
        _index(raw["dimensionPatterns"], "dimensionPatterns")
        _index(raw["ambiguityGroups"], "ambiguityGroups")
        for group in raw["ambiguityGroups"]:
            require(set(group["conceptIds"]) <= set(concepts), "unknown ambiguity concept")
        for pattern in raw["dimensionPatterns"]:
            require(set(pattern["metricConceptIds"]) <= set(concepts), "unknown dimension pattern concept")
            re.compile(pattern["pattern"])
        return deepcopy(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError, re.error) as exc:
        if isinstance(exc, RagContractError):
            raise
        raise RagContractError(f"invalid ontology: {exc}") from exc
