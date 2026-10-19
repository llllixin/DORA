"""Complete current-input identity. Hashes are versions, never historical snapshots."""
from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
import hashlib
import importlib
import inspect
import json
import marshal
import os

from app.series_order import period_key

SCOPE_ID = "dora:default"


def _canonical(value):
    if value is None or isinstance(value, (str, bool)):
        return [type(value).__name__, value]
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("business versions require finite numbers")
        return ["number", "0" if number == 0 else format(number.normalize(), "f")]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("business version dictionary keys must be strings")
        return ["dict", [[key, _canonical(value[key])] for key in sorted(value)]]
    if isinstance(value, (list, tuple)):
        return ["list", [_canonical(item) for item in value]]
    raise ValueError(f"unsupported business version value: {type(value).__name__}")


def canonical_hash(value) -> str:
    payload = json.dumps(_canonical(value), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _release_value(value):
    if value is None or isinstance(value, (str, bool, int, float, Decimal)):
        return value
    if isinstance(value, dict):
        return {str(k): _release_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_release_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_release_value(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    if callable(value):
        return {"callable": getattr(value, "__module__", "") + "." + getattr(value, "__qualname__", type(value).__qualname__)}
    return {"type": type(value).__module__ + "." + type(value).__qualname__}


def _function_release(function):
    return dict(code=marshal.dumps(function.__code__).hex(),
                defaults=_release_value(function.__defaults__),
                keywordDefaults=_release_value(function.__kwdefaults__))


@lru_cache(maxsize=None)
def loaded_code_hash(module_name: str) -> str:
    """Fingerprint loaded code, not a file that might change during a request."""
    module = importlib.import_module(module_name)
    functions = []
    for name, member in inspect.getmembers(module):
        unwrapped = inspect.unwrap(member)
        if inspect.isfunction(unwrapped) and unwrapped.__module__ == module_name:
            functions.append((name, _function_release(unwrapped)))
        elif inspect.isclass(member) and member.__module__ == module_name:
            for method_name, method in inspect.getmembers(member, inspect.isfunction):
                functions.append((name + "." + method_name, _function_release(inspect.unwrap(method))))
            for attribute, descriptor in vars(member).items():
                if isinstance(descriptor, property):
                    for accessor in ("fget", "fset", "fdel"):
                        function = getattr(descriptor, accessor)
                        if function is not None:
                            functions.append((name + "." + attribute + "." + accessor, _function_release(function)))
            constants = {k: _release_value(v) for k, v in vars(member).items()
                         if not k.startswith("_") and isinstance(v, (str, bool, int, float, dict, tuple, list, set, frozenset))}
            functions.append((name + ".constants", constants))
    constants = {name: _release_value(value) for name, value in vars(module).items()
                 if name.isupper() and isinstance(value, (str, bool, int, float, dict, tuple, list, set, frozenset))}
    return canonical_hash(dict(functions=functions, constants=constants))


@lru_cache(maxsize=1)
def ontology_identity() -> str:
    from app.rag.ontology import Ontology
    ontology = Ontology.load()
    return ontology.version + ":" + ontology.content_hash


def reasoning_profile(kind: str | None = None, *, configuration=None, budget_profile=None) -> dict:
    from app.reasoning.llm import SYSTEM_PROMPT, USER_TEMPLATE
    kind = (kind or os.environ.get("DORA_REASONING_PROVIDER") or "template").strip().lower()
    if kind not in {"template", "llm"}:
        raise ValueError("unsupported reasoning provider")
    # Endpoint hash is an identifier; URL credentials/query strings are never emitted.
    from urllib.parse import urlsplit
    configuration = configuration or ((os.environ.get("DORA_LLM_BASE_URL") or "https://api.openai.com/v1"),
                                      None, os.environ.get("DORA_LLM_MODEL") or "gpt-4o-mini")
    endpoint = urlsplit(configuration[0])
    endpoint_id = canonical_hash([endpoint.scheme, endpoint.hostname, endpoint.port, endpoint.path.rstrip("/")])
    from app.runtime.budget import load_profile
    output_cap = (budget_profile or load_profile("reasoning-refresh", kind == "llm")).maxOutputTokensPerCall
    return dict(provider=kind, endpointId=endpoint_id if kind == "llm" else None,
                model=configuration[2] if kind == "llm" else None,
                temperature=0.2 if kind == "llm" else None,
                maxOutputTokens=output_cap if kind == "llm" else None,
                promptHash=canonical_hash([SYSTEM_PROMPT, USER_TEMPLATE]),
                templateHash=loaded_code_hash("app.reasoning.semantics"),
                providerHash=loaded_code_hash("app.reasoning.llm") if kind == "llm" else loaded_code_hash("app.reasoning.provider"))


def build_version(raw: dict, profile: dict | None = None) -> dict:
    rows = [{k: v for k, v in row.items() if k != "rowId"} for row in raw["rows"]]
    rows.sort(key=lambda r: (r["metric_key"], period_key(r["label"]), r["label"], r["dimension"]))
    clusters = sorted(raw["clusters"], key=lambda r: (r["store"], r["region"]))
    rule_rows = sorted(raw.get("ruleRows", []), key=lambda r: r["key"])
    manifest = raw.get("sourceManifest", {})
    from app.engine.engine import RULE_DEFAULTS
    rules = {**RULE_DEFAULTS, **raw["rules"]}
    inputs = dict(rows=rows, clusters=clusters, event=raw["event"], sources=manifest)
    source_hash = canonical_hash({**inputs, "rules": rules, "ruleRows": rule_rows})
    data_revision = "data-v1:" + canonical_hash(dict(scope=raw["scopeId"], epoch=raw["sourceEpoch"],
                                                    generation=raw["generation"], **inputs))
    implementation = raw.get("ruleImplementation") or [loaded_code_hash("app.engine.engine"), loaded_code_hash("app.series_order"), loaded_code_hash("app.business_version")]
    rule_version = "rule-v1:" + canonical_hash(dict(effective=rules, overrides=rule_rows, defaults=RULE_DEFAULTS, implementation=implementation))
    expected_sources = {"metric:" + row["metric_key"] for row in rows}
    if clusters: expected_sources.add("cluster")
    if raw["event"]: expected_sources.add("event")
    if rule_rows: expected_sources.add("rules")
    kinds = {manifest.get(name, "legacy_unknown") for name in expected_sources}
    source_mode = next(iter(kinds)) if len(kinds) == 1 else ("mixed" if kinds else "legacy_unknown")
    version = dict(contractVersion="dora-business-version-v1", scopeId=raw["scopeId"],
                   sourceEpoch=raw["sourceEpoch"], generation=raw["generation"], dataRevision=data_revision,
                   ruleVersion=rule_version, ontologyVersion=raw.get("ontologyIdentity") or ontology_identity(),
                   sourceSetHash=source_hash, reasoningProfile="reason-v1:" + canonical_hash(profile or reasoning_profile()),
                   versionStatus="complete", provenanceStatus="simulated" if kinds == {"sample"} else "incomplete",
                   sourceMode=source_mode)
    version["revision"] = "rev-v1:" + canonical_hash({k: version[k] for k in ("scopeId", "dataRevision", "ruleVersion", "ontologyVersion", "sourceSetHash", "reasoningProfile")})
    return version


def incomplete_version() -> dict:
    return dict(contractVersion="dora-business-version-v1", scopeId=None, sourceEpoch=None,
                generation=None, dataRevision=None, ruleVersion=None, ontologyVersion=None,
                sourceSetHash=None, reasoningProfile=None, revision=None, versionStatus="incomplete",
                provenanceStatus="incomplete", sourceMode="legacy_unknown")


def reprofile_version(version, profile):
    result = deepcopy(version)
    if result["versionStatus"] == "complete":
        result["reasoningProfile"] = "reason-v1:" + canonical_hash(profile)
        result["revision"] = "rev-v1:" + canonical_hash({k: result[k] for k in ("scopeId", "dataRevision", "ruleVersion", "ontologyVersion", "sourceSetHash", "reasoningProfile")})
    return result


def occurrence_id(version: dict, insight_id: str) -> str | None:
    if version.get("versionStatus") != "complete":
        return None
    return "occ-v1:" + canonical_hash([version["scopeId"], version["dataRevision"], version["ruleVersion"], insight_id])


def reasoning_input_hash(insight: dict, snapshot: dict) -> str:
    from app.reasoning.semantics import template_semantics
    return canonical_hash(dict(insight_id=insight["id"], insight_type=insight["type"],
                               **{k: insight[k] for k in ("metric", "delta", "trigger", "factors", "question")},
                               snapshot=snapshot, template=template_semantics(insight["id"], snapshot)))


def cache_key(version: dict, insight_id: str, input_hash: str) -> str:
    return canonical_hash([version["scopeId"], version["revision"], insight_id, input_hash])


class FrozenBusiness:
    """Private copied inputs; each accessor returns a copy and never reads live data."""
    def __init__(self, raw: dict, version: dict, caches=()):
        self._raw = deepcopy(raw)
        self._version = deepcopy(version)
        self._caches = {row["cache_key"]: deepcopy(row) for row in caches}

    @property
    def business_version(self):
        return deepcopy(self._version)

    def export_inputs(self):
        """Independent fact inputs; storage row IDs/counts and model caches are not evidence."""
        raw=deepcopy(self._raw)
        raw.pop('counts',None)
        raw['rows']=[{k:v for k,v in row.items() if k!='rowId'} for row in raw['rows']]
        return raw

    def source_mode_for(self, metric_key):
        value = self._raw.get('sourceManifest', {}).get('metric:'+metric_key, 'legacy_unknown')
        return deepcopy(value.get('mode','legacy_unknown') if isinstance(value,dict) else value)

    def get_series(self, key):
        rows = [r for r in self._raw["rows"] if r["metric_key"] == key]
        rows.sort(key=lambda r: (period_key(r["label"]), r["label"], r["dimension"]))
        return [{k: r[k] for k in ("label", "value", "dimension", "unit")} for r in rows]

    def get_cluster_stores(self):
        return deepcopy(sorted(self._raw["clusters"], key=lambda r: (r["store"], r["region"])))

    def get_rules(self):
        return deepcopy(self._raw["rules"])

    def with_rules(self, rules):
        raw = deepcopy(self._raw)
        raw["rules"] = deepcopy(rules)
        raw["ruleRows"] = [dict(key=k, value=str(v), value_type=type(v).__name__) for k, v in rules.items()]
        return FrozenBusiness(raw, build_version(raw))

    def with_profile(self, profile):
        return FrozenBusiness(self._raw, reprofile_version(self._version, profile), self._caches.values())

    @property
    def current_counts(self):
        return deepcopy(self._raw["counts"])

    def get_latest_update(self):
        return deepcopy(self._raw["event"])

    def get_reasoning(self, insight_id, input_hash):
        row = self._caches.get(cache_key(self._version, insight_id, input_hash))
        if row and row["business_version"] == self._version and row["input_hash"] == input_hash:
            return deepcopy(row)
        return None
