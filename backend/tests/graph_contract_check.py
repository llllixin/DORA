"""Protect graph identities and the finite public read contract."""
import unittest
from pydantic import ValidationError

try:
    from app.graph import contracts as api
except ImportError:
    api = None


class GraphContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(api, 'A09 graph contracts are not implemented')

    def test_numeric_identity_and_untrusted_values(self):
        self.assertEqual(api.identity('entity', {'x': 1, 'zero': -0.0}),
                         api.identity('entity', {'zero': 0, 'x': 1.0}))
        for value in [float('nan'), float('inf'), {1: 'bad'}]:
            with self.assertRaises(api.GraphError): api.identity('entity', value)
        self.assertNotEqual(api.identity('entity', {'scope': 'a'}), api.identity('entity', {'scope': 'b'}))

    def test_tampered_content_rejected(self):
        row = api.seal('entity', {'scopeId': 'dora:default', 'type': 'Snapshot', 'attributes': {'x': 1}})
        api.validate('entity', row)
        row['attributes']['x'] = 2
        with self.assertRaises(api.GraphError): api.validate('entity', row)

    def test_strict_read_request_and_history(self):
        self.assertFalse(api.GraphRequest(entityId='x').includeSimulated)
        for kwargs in [{'maxHops': 3}, {'maxHops': True}, {'scopeId': 'other'},
                       {'mode': 'historical'}, {'mode': 'current', 'batchId': 'x'},
                       {'relationTypes': ['not_registered']}, {'direction': 'sql'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                api.GraphRequest(entityId='x', **kwargs)

    def test_data_only_pointer(self):
        self.assertEqual(api.resolve_pointer({'a/b': [{'x~': 18.1}]}, '/a~1b/0/x~0'), 18.1)
        for pointer in ['__class__', '/__class__', '/a~2b', '/a~1b/999']:
            with self.assertRaises(api.GraphError): api.resolve_pointer({'a/b': []}, pointer)

    def test_registry_direction_evidence_and_v2_remain(self):
        from app.graph.registry import REGISTRY, check_relation
        from app.rag.ontology import Ontology
        before = Ontology.load().content_hash
        self.assertEqual(len(REGISTRY), 13)
        check_relation('opened_from', 'ActionCase', 'InsightOccurrence')
        with self.assertRaises(api.GraphError): check_relation('opened_from', 'Snapshot', 'ActionCase')
        self.assertEqual(Ontology.load().content_hash, before)
        self.assertTrue(all(r['evidenceRequired'] and not r['causalityAllowed'] for r in REGISTRY.values()))


if __name__ == '__main__': unittest.main()
