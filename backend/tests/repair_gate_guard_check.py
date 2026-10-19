"""The repair gate must reject user/ambiguous database and API targets."""
import unittest
from unittest.mock import patch
from tests.repair_gate import validate_environment,main
VALID={'DATABASE_URL':'postgresql+psycopg://dora_repair:fixture@127.0.0.1:55460/dora_repair','DORA_API_BASE':'http://127.0.0.1:8060/api'}

class RepairGateGuards(unittest.TestCase):
    def test_exact_disposable_targets_accepted_without_io(self):
        self.assertEqual(validate_environment(VALID),(VALID['DATABASE_URL'],8060))
    def test_unsafe_database_targets_rejected(self):
        for url in ('','postgresql+psycopg://dora:pw@127.0.0.1:5432/dora',VALID['DATABASE_URL'].replace('55460','55459'),VALID['DATABASE_URL'].replace('/dora_repair','/dora'),VALID['DATABASE_URL'].replace('127.0.0.1','remote.example'),VALID['DATABASE_URL']+'?hostaddr=127.0.0.1'):
            with self.subTest(url=url),self.assertRaises(ValueError):validate_environment({**VALID,'DATABASE_URL':url})
    def test_unsafe_api_targets_rejected(self):
        for api in ('','http://127.0.0.1:8000/api','https://127.0.0.1:8060/api','http://localhost:8060/api','http://127.0.0.1:8060/api?scope=any'):
            with self.subTest(api=api),self.assertRaises(ValueError):validate_environment({**VALID,'DORA_API_BASE':api})
    def test_invalid_environment_stops_before_subprocess_or_seed(self):
        with patch.dict('os.environ',{'DATABASE_URL':'','DORA_API_BASE':''}),patch('tests.repair_gate.subprocess.run',side_effect=AssertionError('must not mutate')):
            with self.assertRaises(ValueError):main()

if __name__=='__main__':unittest.main()
