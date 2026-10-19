import importlib
import json
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from tests.evidence_test_support import frozen_inputs,raw_inputs


class EvidenceContractChecks(unittest.TestCase):
    def api(self):
        self.assertTrue((Path(__file__).parents[1]/'app/evidence/contracts.py').exists(), 'immutable evidence builder not implemented')
        return importlib.import_module('app.evidence.contracts')

    def test_same_content_identity(self):
        c=self.api();f=frozen_inputs()
        with patch('app.db.make_session',side_effect=AssertionError('DB')),patch('urllib.request.urlopen',side_effect=AssertionError('network')):
            a=c.build_snapshot(f);b=c.build_snapshot(f)
        self.assertEqual(a['snapshotId'],b['snapshotId']);self.assertTrue(a['snapshotId'].startswith('snap-v1:'))
        a['payload']['rawSeries'][0]['value']=0
        self.assertNotEqual(a['payload'],b['payload'])

    def test_same_values_new_generation_new_identity(self):
        c=self.api();self.assertNotEqual(c.build_snapshot(frozen_inputs())['snapshotId'],c.build_snapshot(frozen_inputs(2))['snapshotId'])

    def test_profile_change_keeps_fact_identity(self):
        c=self.api();f=frozen_inputs();g=f.with_profile({'model':'another-model'})
        self.assertNotEqual(f.business_version['revision'],g.business_version['revision'])
        self.assertEqual(c.build_snapshot(f)['snapshotId'],c.build_snapshot(g)['snapshotId'])
        self.assertNotIn('reasoningProfile',c.build_snapshot(g)['factVersion'])

    def test_export_is_complete_and_deep_copied(self):
        c=self.api();f=frozen_inputs();raw=f.export_inputs();raw['rows'][0]['value']=123456
        self.assertNotEqual(raw,f.export_inputs());self.assertNotIn('counts',raw)
        p=c.build_snapshot(f)['payload'];self.assertTrue(p['rawSeries']);self.assertTrue(p['rawClusters'])
        self.assertEqual(p['updateEvent']['updated'],'fixture:observed');self.assertTrue(p['effectiveRules'])
        self.assertTrue(p['hasSimulatedInputs']);self.assertEqual(p['sourceLevel'],'simulated')
        self.assertIsNone(p['rowLocators'][0]['originalEnterpriseFile'])

    def test_units_labels_and_nonfinite_numbers(self):
        c=self.api();f=frozen_inputs();p=c.build_snapshot(f)['payload']
        self.assertEqual({r['unit'] for r in p['rawSeries']},{r['unit'] for r in raw_inputs()['rows']})
        for invalid in (float('nan'),float('inf'),float('-inf')):
            with self.assertRaises(c.EvidenceError):c.payload_size({'value':invalid})

    def test_period_labels_do_not_invent_year(self):
        c=self.api();p=c.build_snapshot(frozen_inputs())['payload']
        self.assertEqual({r['label'] for r in p['rawSeries']},{r['label'] for r in raw_inputs()['rows']})
        self.assertIn('business_year_unverified',p['unknowns'])

    def test_exact_payload_size_boundary(self):
        c=self.api();base={'x':''};size=len(json.dumps(base,sort_keys=True,separators=(',',':')).encode())
        self.assertEqual(c.payload_size({'x':'a'*(2097152-size)}),2097152)
        with self.assertRaises(c.EvidenceError) as e:c.payload_size({'x':'a'*(2097153-size)})
        self.assertEqual(e.exception.status_code,413)

    def test_absent_signal_has_no_fake_occurrence(self):
        c=self.api();p=c.build_snapshot(frozen_inputs(2,margin=19.0))['payload']
        self.assertFalse(any(i['id']=='p1' for i in p['factInsights']))
        self.assertFalse(any(e['insightTypeId']=='p1' for e in p['storedEvidence']))


if __name__=='__main__':unittest.main()
