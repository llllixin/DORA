"""Graph-only instance catalog; never mutates ontology v2 or its expansion."""
from app.business_version import canonical_hash
from app.graph.contracts import GraphError

SCHEMA_VERSION = 'business-graph-schema-v1'
_TYPES = {
    'applies_to': ('Rule', 'Metric'),
    'observed_as': ('Metric', 'MetricObservation'),
    'produced_occurrence': ('Rule', 'InsightOccurrence'),
    'supported_by': ('InsightOccurrence', 'Snapshot'),
    'monitors': ('WatchTarget', 'Metric'),
    'emitted': ('WatchTarget', 'WatchEvent'),
    'opened_from': ('ActionCase', 'InsightOccurrence'),
    'lesson_from': ('Lesson', 'ActionCase'),
    'captured_in': ('MetricObservation', 'Snapshot'),
    'event_evidenced_by': ('WatchEvent', 'Snapshot'),
    'opened_with': ('ActionCase', 'Snapshot'),
    'verified_with': ('ActionCase', 'Snapshot'),
    'event_matched': ('WatchEvent', 'InsightOccurrence'),
}
REGISTRY = {key: {'domain': [a], 'range': [b], 'evidenceRequired': True, 'causalityAllowed': False}
            for key, (a, b) in _TYPES.items()}
SCHEMA_HASH = canonical_hash([SCHEMA_VERSION, REGISTRY])


def check_relation(kind, source_type, target_type):
    rule = REGISTRY.get(kind)
    if not rule or source_type not in rule['domain'] or target_type not in rule['range']:
        raise GraphError('graph_relation_invalid', 409)
