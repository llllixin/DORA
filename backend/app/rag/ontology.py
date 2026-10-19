"""Reviewed semantics, physical read bindings and controlled one-hop expansion."""
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any

from app.rag.contracts import KNOWLEDGE_ROOT, RagContractError
from app.rag.ontology_contracts import content_hash, require, validate_ontology


def _occurrences(text: str, term: str):
    expression = re.escape(term)
    if term.isascii():
        expression = r"(?<![A-Za-z0-9_])" + expression + r"(?![A-Za-z0-9_])"
    return [(m.start(), m.end()) for m in re.finditer(expression, text, flags=re.IGNORECASE)]


class Ontology:
    def __init__(self, raw: dict, *, allow_candidate: bool = False):
        self.raw = validate_ontology(raw, allow_candidate=allow_candidate)
        self.concepts = {c["id"]: c for c in self.raw["concepts"]}
        self.relations = self.raw["relations"]
        self.catalog = {r["id"]: r for r in self.raw["relationTypes"]}
        self.version = self.raw["ontologyVersion"]
        self.content_hash = content_hash(self.raw)
        self.alias_to_id = {name.casefold(): c["id"] for c in self.concepts.values()
                            for name in [c["name"], *c["aliases"]]}

    @classmethod
    def from_dict(cls, raw: dict, *, allow_candidate: bool = False) -> "Ontology":
        return cls(raw, allow_candidate=allow_candidate)

    @classmethod
    def load(cls, path: Path | None = None) -> "Ontology":
        source = path or KNOWLEDGE_ROOT / "ontology/ontology.json"
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
            ontology = cls(raw)
            directory = KNOWLEDGE_ROOT / "ontology/releases"
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            publication = manifest[ontology.version]
            release_path = (directory / publication["file"]).resolve()
            require(release_path.is_relative_to(directory.resolve()), "invalid release path")
            release = json.loads(release_path.read_text(encoding="utf-8"))
            require(ontology.content_hash == publication["contentHash"] == content_hash(release), "ontology publication hash mismatch")
            return ontology
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise RagContractError(f"无法读取已发布 ontology: {exc}") from exc

    def resolve(self, query: str, purpose: str = "knowledge") -> dict[str, Any]:
        if not isinstance(query, str) or purpose not in {"knowledge", "metric", "watch"}:
            raise ValueError("query 必须为字符串；purpose 为 knowledge/metric/watch")
        text = query.strip()
        spans = []
        regions = set()
        for cid, concept in self.concepts.items():
            for name in [concept["name"], *concept["aliases"]]:
                for start, end in _occurrences(text, name):
                    if concept["type"] == "Region":
                        regions.add(cid)
                    elif concept["type"] != "Dimension":
                        spans.append((start, end, cid))
        for pattern in self.raw["dimensionPatterns"]:
            if pattern["id"] == "supplier-price":
                spans.extend((m.start(), m.end(), cid) for m in re.finditer(pattern["pattern"], text)
                             for cid in pattern["metricConceptIds"])
        selected = []
        for span in sorted(set(spans), key=lambda v: (-(v[1] - v[0]), v[0], v[2])):
            if not any(span[0] < old[1] and old[0] < span[1] for old in selected):
                selected.append(span)
        matched = {cid for _, _, cid in selected}
        ambiguous = []
        for group in self.raw["blockedTerms"]:
            for term in group["terms"]:
                if any(not any(a <= start and end <= b for a, b, _ in selected)
                       for start, end in _occurrences(text, term)):
                    ambiguous.append({"reasonCode": group["reason"], "question": group["clarification"]})
                    break
        stores = list(dict.fromkeys(m.group() for m in re.finditer(r"门店\s*[0-9]+", text)))
        suppliers = list(dict.fromkeys(m.group() for m in re.finditer(r"供应商[A-Za-z0-9]+", text)))
        metrics = {cid for cid in matched if self.concepts[cid]["type"] == "Metric"}
        if len(metrics) == 1 and "metric.orders" in metrics and len(regions) == 1:
            view = next((v for v in self.raw["regionViews"] if v["baseConceptId"] == "metric.orders" and v["regionId"] in regions), None)
            if view:
                matched.remove("metric.orders")
                matched.add(view["viewConceptId"])
                metrics = {view["viewConceptId"]}
        warnings = []
        binding = None
        primary = next(iter(metrics)) if len(metrics) == 1 else None
        for cid in sorted(metrics):
            if self.concepts[cid]["metricBinding"] is None:
                ambiguous.append({"reasonCode": "unbound_metric", "question": f"请确认{self.concepts[cid]['name']}的项目口径与数据来源。"})
        read_targets = {cid for cid in matched if self.concepts[cid]["type"] in {"Metric", "Collection"}}
        if purpose != "knowledge" and len(read_targets) > 1:
            ambiguous.append({"reasonCode": "multiple_metric_targets", "question": "请选择一个指标与范围，或将问题拆分。"})
        # Knowledge comparisons may describe several registered regions without
        # requesting a single physical read. Metric/watch still require one scope.
        if primary and not ambiguous and (purpose != "knowledge" or len(regions) <= 1):
            binding = deepcopy(self.concepts[primary]["metricBinding"])
            region_names = {self.concepts[cid]["name"] for cid in regions}
            policy = binding["dimensionPolicy"]
            reason = None
            if len(region_names) > 1 or len(stores) > 1 or len(suppliers) > 1:
                reason = "multiple_dimension_values"
            elif policy in {"fixed", "fixed_with_east_view"}:
                if stores or suppliers or (region_names and region_names != {binding["dimension"]}):
                    reason = "unsupported_dimension"
            elif policy == "store_or_all_rows":
                if region_names or suppliers:
                    reason = "national_aggregate_not_defined" if "全国" in region_names else "unsupported_dimension"
                else:
                    binding["dimension"] = stores[0] if stores else None
                    if not stores:
                        warnings.append("all_rows_only_no_aggregate")
            elif policy == "supplier_or_all_rows":
                if region_names or stores:
                    reason = "unsupported_dimension"
                else:
                    binding["dimension"] = suppliers[0] if suppliers else None
                    if not suppliers:
                        warnings.append("all_rows_only_no_single_supplier")
            if reason:
                ambiguous.append({"reasonCode": reason, "question": "请明确一个有来源且受支持的指标维度；不能用默认范围替代。"})
            if primary == "metric.margin":
                warnings.append("financial_basis_unconfirmed")
        if ambiguous or purpose == "knowledge":
            binding = None
        status = "clarification_required" if ambiguous else ("resolved" if matched else "no_match")
        return {"semanticStatus": status, "conceptIds": sorted(matched), "primaryMetricId": primary,
                "regionIds": sorted(regions), "dimensionValues": stores + suppliers,
                "metricBinding": binding, "ambiguities": ambiguous, "warnings": warnings,
                "ontologyVersion": self.version, "ontologyHash": self.content_hash}

    def expand(self, query: str, *, enable_expansion: bool = True) -> dict[str, Any]:
        semantic = self.resolve(query)
        matched = set(semantic["conceptIds"])
        related, relation_ids = set(), []
        if semantic["semanticStatus"] != "clarification_required" and enable_expansion:
            for relation in self.relations:
                policy = self.catalog[relation["type"]]["queryExpansion"]
                source, target = relation["from"], relation["to"]
                used = False
                if source in matched and policy["fromMatched"]:
                    related.add(target); used = True
                if target in matched and policy["toMatched"]:
                    related.add(source); used = True
                if used:
                    relation_ids.append(relation["id"])
        related -= matched
        terms = []
        if semantic["semanticStatus"] != "clarification_required":
            for cid in sorted(matched | related):
                concept = self.concepts[cid]
                terms.extend([concept["name"], *concept["aliases"]])
        return {"concept_ids": sorted(matched), "related_concept_ids": sorted(related),
                "terms": list(dict.fromkeys(terms)), "relationIds": sorted(relation_ids),
                **{key: semantic[key] for key in ["semanticStatus", "ambiguities", "ontologyVersion", "ontologyHash", "warnings"]}}
