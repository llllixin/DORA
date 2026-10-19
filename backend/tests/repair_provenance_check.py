"""Regression for partial legacy uploads and immutable provenance validation."""
from copy import deepcopy
import unittest
from app.business_version import FrozenBusiness,build_version,canonical_hash
from app.evidence.contracts import build_snapshot,validate_stored_snapshot,EvidenceError
from tests.evidence_test_support import raw_inputs

class ProvenanceRepairChecks(unittest.TestCase):
    def snapshot(self,raw):return build_snapshot(FrozenBusiness(raw,build_version(raw)))
    def test_partial_upload_does_not_promote_unknown_inputs(self):
        raw=raw_inputs();raw['sourceManifest']={'metric:margin':'uploaded','event':'uploaded'}
        stored=self.snapshot(raw)
        self.assertEqual(stored['sourceLevel'],'legacy_unknown')
        self.assertFalse(stored['payload']['hasSimulatedInputs'])
    def test_each_actual_category_requires_manifest(self):
        for missing in ('metric:returns','rules','cluster','event'):
            with self.subTest(missing=missing):
                raw=raw_inputs();raw['sourceManifest']={k:'uploaded' for k in raw['sourceManifest']};raw['sourceManifest'].pop(missing)
                self.assertEqual(self.snapshot(raw)['sourceLevel'],'legacy_unknown')
    def test_only_actual_sources_determine_grade(self):
        raw=raw_inputs();raw['sourceManifest']={k:'uploaded' for k in raw['sourceManifest']};raw['sourceManifest']['metric:removed']='sample'
        self.assertEqual(self.snapshot(raw)['sourceLevel'],'reported')
        raw['sourceManifest']['metric:margin']='sample'
        self.assertEqual(self.snapshot(raw)['sourceLevel'],'simulated')
    def test_hash_valid_old_wrong_grade_is_rejected_without_rewriting(self):
        raw=raw_inputs();raw['sourceManifest']={'metric:margin':'uploaded'};stored=self.snapshot(raw)
        stored['sourceLevel']=stored['payload']['sourceLevel']='reported'
        sha=canonical_hash(stored['payload']);stored['snapshotId']='snap-v1:'+sha;stored['payloadHash']=sha;original=deepcopy(stored)
        with self.assertRaisesRegex(EvidenceError,'snapshot_integrity_error'):
            validate_stored_snapshot(stored,scope_id=raw['scopeId'])
        self.assertEqual(stored,original)
    def test_valid_snapshot_still_reads(self):
        raw=raw_inputs();stored=self.snapshot(raw)
        self.assertEqual(validate_stored_snapshot(stored,scope_id=raw['scopeId']),stored)

if __name__=='__main__':unittest.main()
